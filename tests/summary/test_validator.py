import json
from datetime import UTC, datetime
from typing import Any

import pytest

from app.services.summary.claims import Claim
from app.services.summary.filters import Candidate
from app.services.summary.selection import Selected
from app.services.summary.validator import (
    InvalidLlmOutputError,
    ValidatedSummary,
    validate_summary,
)

CLAIMS = [Claim(id="clm_1", text="Phòng view biển", source="caption")]


def _selected(
    author: str,
    text: str = "Phòng sạch, view đẹp",
    *,
    is_first_hand: bool = False,
    is_suspect: bool = False,
    supporters: frozenset[str] = frozenset(),
) -> Selected:
    candidate = Candidate(
        author_id=author,
        comment_ids=(f"cmt_{author}",),
        text=text,
        text_norm="",
        like_count=0,
        created_at=datetime(2026, 11, 5, tzinfo=UTC),
        is_suspect=is_suspect,
        supporters=supporters,
    )
    return Selected(candidate=candidate, tier=3, is_first_hand=is_first_hand, tokens=10, text=text)


BY_CODE = {
    "c1": _selected("a", is_first_hand=True),
    "c2": _selected("b", is_first_hand=True),
    "c3": _selected("c"),
    "c4": _selected("d", "Ăn buffet xong bị ngộ độc, đau bụng cả đêm"),  # rule safety flag
    "c5": _selected("e", "Video edit đỉnh quá"),
}


def _output(**sections: Any) -> str:
    empty: dict[str, Any] = {
        "excluded": {"video_reaction_ids": [], "speculation_ids": []},
        "safety_mentions": [],
        "pros": [],
        "cons": [],
        "reality_gaps": [],
        "topics": [],
    }
    return json.dumps(empty | sections)


def _pro(ids: list[str], text: str = "View biển đẹp.") -> dict[str, Any]:
    return {"comment_ids": ids, "aspect": "canh_quan", "text": text}


def _run(raw: str, by_code: dict[str, Selected] | None = None) -> ValidatedSummary:
    return validate_summary(raw, by_code or BY_CODE, CLAIMS)


def _rules(summary: ValidatedSummary) -> set[str]:
    return {f.rule for f in summary.report}


# V1


def test_v1_valid_output_maps_codes_back_to_real_ids() -> None:
    summary = _run(_output(pros=[_pro(["c1", "c2"])]))

    assert summary.pros[0].comment_ids == ("cmt_a", "cmt_b")
    assert summary.report == []


def test_v1_broken_schema_fails_the_whole_run() -> None:
    with pytest.raises(InvalidLlmOutputError):
        _run('{"pros": "không phải JSON đúng schema"}')


def test_v1_unknown_ids_and_claims_are_dropped() -> None:
    gap = {"claim_id": "clm_9", "comment_ids": ["c1", "c2"], "reality": "Phòng nhìn ra núi."}

    summary = _run(_output(pros=[_pro(["c1", "c2", "c99"])], reality_gaps=[gap]))

    assert summary.pros[0].comment_ids == ("cmt_a", "cmt_b")
    assert summary.reality_gaps == []
    assert _rules(summary) == {"V1"}


def test_v1_too_many_items_or_ids_are_trimmed_not_failed() -> None:
    """A JSON mode without strict schema ignores maxItems; one extra item must not fail the run."""
    many_ids = ["c1", "c2"] + [f"c{i}" for i in range(100, 160)]  # 62 ids, 2 known
    pros = [_pro(["c1", "c2"], f"Ý {i}.") for i in range(7)] + [_pro(many_ids)]

    summary = _run(_output(pros=pros))

    assert [p.text for p in summary.pros] == [f"Ý {i}." for i in range(5)]  # ties keep order
    trims = [f.detail for f in summary.report if f.action == "trim"]
    assert trims == [
        "62 ids, kept 50",  # the extra item is checked like the others
        "8 items, kept 5: dropped ['canh_quan (2)', 'canh_quan (2)', 'canh_quan (2)']",
    ]


def test_v1_overflow_keeps_one_point_per_aspect_before_a_second_of_the_same() -> None:
    """Large post (BAO_CAO): the LLM split scenery into 4 points and the first 5 lost 4 aspects."""
    by_code = {f"c{i}": _selected(f"u{i}") for i in range(1, 21)}

    def point(aspect: str, people: int, start: int) -> dict[str, Any]:
        ids = [f"c{i}" for i in range(start, start + people)]
        return {"comment_ids": ids, "aspect": aspect, "text": f"{aspect} {people}."}

    pros = [point("canh_quan", 9, 1), point("canh_quan", 8, 1), point("canh_quan", 7, 1)]
    pros += [point("canh_quan", 6, 1), point("phong_o", 3, 10), point("phuc_vu", 5, 13)]
    pros += [point("gia_ca", 2, 18), point("do_an", 4, 15)]

    summary = _run(_output(pros=pros), by_code)

    assert [(p.aspect, p.people) for p in summary.pros] == [
        ("canh_quan", 9),
        ("phuc_vu", 5),
        ("do_an", 4),
        ("phong_o", 3),
        ("gia_ca", 2),
    ]


def test_v1_second_point_of_an_aspect_fills_a_free_slot() -> None:
    by_code = {f"c{i}": _selected(f"u{i}") for i in range(1, 7)}
    pros = [
        {"comment_ids": ["c1", "c2"], "aspect": "canh_quan", "text": "View biển."},
        {"comment_ids": ["c3", "c4", "c5"], "aspect": "canh_quan", "text": "Hồ bơi đẹp."},
    ]

    summary = _run(_output(pros=pros), by_code)

    assert [p.text for p in summary.pros] == ["View biển.", "Hồ bơi đẹp."]  # under the cap


def test_v1_broken_extra_item_is_dropped_and_runaway_output_is_capped() -> None:
    pros = [_pro(["c1", "c2"], f"Ý {i}.") for i in range(5)]
    pros += [{"comment_ids": ["c1", "c2"], "aspect": "khong_co", "text": "x"}]
    pros += [_pro(["c1", "c2"], f"Thêm {i}.") for i in range(20)]

    summary = _run(_output(pros=pros))

    assert len(summary.pros) == 5
    details = [f.detail for f in summary.report if f.rule == "V1"]
    assert details[0] == "26 items, kept 15"
    assert "extra item breaks the schema" in details


def test_v1_too_many_ids_in_one_item_keeps_the_first_fifty() -> None:
    by_code = {f"c{i}": _selected(f"u{i}") for i in range(1, 61)}
    ids = [f"c{i}" for i in range(1, 61)]

    summary = _run(_output(pros=[_pro(ids)]), by_code)

    assert summary.pros[0].people == 50
    assert [f.detail for f in summary.report if f.action == "trim"] == ["60 ids, kept 50"]


@pytest.mark.parametrize(
    "raw",
    [
        "not json at all",
        _output(pros=[{"comment_ids": ["c1", "c2"], "aspect": "khop_video", "text": "x"}]),
        _output(pros=[{**_pro(["c1", "c2"]), "people": 3}]),
    ],
)
def test_v1_real_schema_errors_still_fail(raw: str) -> None:
    with pytest.raises(InvalidLlmOutputError):
        _run(raw)


# V2


def test_v2_excluded_comments_cannot_support_a_point() -> None:
    excluded = {"video_reaction_ids": ["c5"], "speculation_ids": ["c3"]}

    summary = _run(_output(excluded=excluded, pros=[_pro(["c1", "c3", "c5"])]))

    assert summary.pros == []  # only c1 left: one person
    assert {"V2", "V3"} <= _rules(summary)


def test_v2_point_survives_when_enough_evidence_is_not_excluded() -> None:
    excluded = {"video_reaction_ids": ["c5"], "speculation_ids": []}

    summary = _run(_output(excluded=excluded, pros=[_pro(["c1", "c2", "c5"])]))

    assert summary.pros[0].people == 2


# V3


def test_v3_one_person_is_not_a_point_even_with_two_comments() -> None:
    same_author = {"c1": _selected("a"), "c2": _selected("a")}

    summary = _run(_output(cons=[_pro(["c1", "c2"], "Phòng cũ.")]), same_author)

    assert summary.cons == []
    assert _rules(summary) == {"V3"}


def test_v3_agreeing_reply_counts_and_suspect_copy_does_not() -> None:
    by_code = {
        "c1": _selected("a", supporters=frozenset({"z"})),
        "c2": _selected("b", is_suspect=True),
    }

    summary = _run(_output(cons=[_pro(["c1", "c2"], "Phòng cũ.")]), by_code)

    assert summary.cons[0].people == 2  # a + supporter z; suspect b not counted


# V4


def test_v4_gaps_on_the_same_claim_merge_then_need_two_first_hand_writers() -> None:
    gaps = [
        {"claim_id": "clm_1", "comment_ids": ["c1"], "reality": "Phòng nhìn ra núi."},
        {"claim_id": "clm_1", "comment_ids": ["c2", "c3"], "reality": "View núi, không biển."},
    ]

    summary = _run(_output(reality_gaps=gaps))

    [gap] = summary.reality_gaps
    assert gap.comment_ids == ("cmt_a", "cmt_b")  # c3 is not first-hand
    assert gap.reality == "View núi, không biển."  # sentence of the bigger item
    assert gap.claim == "Phòng view biển"
    assert gap.people == 2


def test_v4_one_first_hand_writer_is_not_enough() -> None:
    gap = {"claim_id": "clm_1", "comment_ids": ["c1", "c3"], "reality": "Phòng nhìn ra núi."}

    summary = _run(_output(reality_gaps=[gap]))

    assert summary.reality_gaps == []


# V5


def test_v5_safety_flagged_comment_is_removed_and_llm_only_safety_is_a_hint() -> None:
    mentions = [
        {"comment_ids": ["c4"], "text": "Có người bị ngộ độc."},  # rules flagged it already
        {"comment_ids": ["c3"], "text": "Có thể không an toàn."},  # rules did not
    ]

    summary = _run(_output(safety_mentions=mentions, cons=[_pro(["c3", "c4"], "Đồ ăn tệ.")]))

    assert summary.cons == []
    assert summary.safety_hints == ("cmt_c",)
    assert "V5" in _rules(summary)


def test_v5_no_hint_when_rules_agree() -> None:
    mentions = [{"comment_ids": ["c4"], "text": "Có người bị ngộ độc."}]

    assert _run(_output(safety_mentions=mentions)).safety_hints == ()


# V6


@pytest.mark.parametrize(
    "text",
    [
        "Nhiều người khen view đẹp.",
        "3 bạn thấy phòng sạch.",
        "70% bình luận khen.",
        "Phòng chỉ 500k một đêm.",
        "Đặt qua 0912345678 rẻ hơn.",
    ],
)
def test_v6_counts_money_and_pii_written_by_the_llm_drop_the_point(text: str) -> None:
    summary = _run(_output(pros=[_pro(["c1", "c2"], text)]))

    assert summary.pros == []
    assert _rules(summary) == {"V6"}


@pytest.mark.parametrize(
    "text", ["Nên đến trước 7h để tránh đông.", "Bãi biển ít người, nước trong."]
)
def test_v6_times_and_crowd_words_are_allowed(text: str) -> None:
    assert _run(_output(pros=[_pro(["c1", "c2"], text)])).pros[0].people == 2


# V8


def test_v8_topics_with_the_same_label_merge_and_reach_two_people() -> None:
    topics = [
        {"comment_ids": ["c1"], "label": "Giá vé", "summary": "Hỏi giá vé."},
        {"comment_ids": ["c3"], "label": "giá vé ", "summary": "Hỏi vé cáp treo."},
    ]

    [topic] = _run(_output(topics=topics)).topics

    assert topic.comment_ids == ("cmt_a", "cmt_c")
    assert topic.people == 2


def test_v8_topic_is_dropped_without_two_people_or_with_a_count() -> None:
    topics = [
        {"comment_ids": ["c1"], "label": "Đường đi", "summary": "Hỏi đường."},
        {"comment_ids": ["c1", "c2"], "label": "Giá", "summary": "Đa số thấy đắt."},
    ]

    summary = _run(_output(topics=topics))

    assert summary.topics == []
    assert {"V6", "V8"} <= _rules(summary)


def test_v6_bad_short_form_is_dropped_but_the_point_stays() -> None:
    pros = [
        {**_pro(["c1", "c2"], "View biển đẹp."), "short": "view biển đẹp"},
        {**_pro(["c1", "c2"], "Hồ bơi rộng."), "short": "nhiều người khen hồ bơi"},  # a count
        {**_pro(["c1", "c2"], "Bãi biển sạch."), "short": "bãi biển " + "rất " * 15 + "sạch"},
        _pro(["c1", "c2"], "Phòng mới."),  # no short at all (summary.v2 output)
    ]

    summary = _run(_output(pros=pros))

    assert [p.short for p in summary.pros] == ["view biển đẹp", None, None, None]
    assert [f.action for f in summary.report] == ["drop_short", "drop_short"]


def test_v6_mosquitoes_at_night_is_not_a_count_of_people() -> None:
    """Seed s15: "muỗi ban đêm" and "mười bạn" are both "muoi ban" without diacritics."""
    con = {
        "comment_ids": ["c1", "c2"],
        "aspect": "ve_sinh",
        "text": "Có nhiều muỗi, phải bật vợt muỗi ban đêm.",
    }

    summary = _run(_output(cons=[con]))

    assert [p.aspect for p in summary.cons] == ["ve_sinh"]


def test_v1_a_missing_list_section_reads_as_empty_but_excluded_is_required() -> None:
    """Large post: the LLM once left out `topics` and the whole run failed."""
    data = json.loads(_output(pros=[_pro(["c1", "c2"])]))
    del data["topics"]

    summary = _run(json.dumps(data))

    assert [p.text for p in summary.pros] == ["View biển đẹp."] and summary.topics == []
    assert [f.detail for f in summary.report] == ["missing, read as empty"]
    del data["excluded"]
    with pytest.raises(InvalidLlmOutputError):
        _run(json.dumps(data))
