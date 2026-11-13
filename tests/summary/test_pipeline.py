import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from app.clients.llm.base import LlmResult
from app.clients.llm.fake import FakeLlmClient
from app.clients.llm.guarded import LlmUnavailableError
from app.services.summary.comment_classifier import CommentClassifier, CommentLabels
from app.services.summary.estimates import PostStats
from app.services.summary.label_store import StoredSafety
from app.services.summary.pipeline import (
    MAX_SUMMARY_CHARS,
    SummaryRun,
    _summary_text,  # pyright: ignore[reportPrivateUsage]
    run_summary,
)
from app.services.summary.schemas import CommentIn, ItineraryItemIn
from app.services.summary.validator import RealityGapPoint, SummaryPoint, ValidatedSummary

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)
TEXTS = [
    "Phòng rộng, view biển nhìn thẳng ra bãi tắm rất đẹp",
    "Mình ở 2 đêm, nhân viên lễ tân nhiệt tình hỗ trợ check-in sớm",
    "Bữa sáng nhiều món, hải sản tươi, đáng tiền",
    "Hồ bơi vô cực chụp ảnh sống ảo cực chill lúc hoàng hôn",
    "Đi taxi từ sân bay mất tầm 20 phút, đường dễ tìm",
]
ITINERARY = [ItineraryItemIn(kind="service", place_name="Vinpearl Đà Nẵng")]


def _comment(i: int, body: str) -> CommentIn:
    return CommentIn(
        comment_id=f"cmt_{i}",
        author_id=f"user_{i}",
        body=body,
        status="visible",
        created_at=NOW - timedelta(days=1, minutes=i),
    )


def _comments(n: int = 5) -> list[CommentIn]:
    return [_comment(i, TEXTS[i]) for i in range(n)]


def _llm(**sections: object) -> FakeLlmClient:
    empty: dict[str, object] = {
        "excluded": {"video_reaction_ids": [], "speculation_ids": []},
        "safety_mentions": [],
        "pros": [],
        "cons": [],
        "reality_gaps": [],
        "topics": [],
    }
    return FakeLlmClient(json.dumps(empty | sections))


PROS = [{"comment_ids": ["c1", "c2", "c3"], "aspect": "canh_quan", "text": "View biển đẹp"}]


NO_LABEL = CommentLabels(
    is_experienced=False,
    is_first_hand=False,
    is_hearsay=False,
    is_complaint=False,
    is_praise=False,
    is_video_reaction=False,
)
FIRST_HAND = replace(NO_LABEL, is_experienced=True, is_first_hand=True)
HEARSAY = replace(NO_LABEL, is_experienced=True, is_hearsay=True)
REACTION = replace(NO_LABEL, is_video_reaction=True)


@dataclass
class FakeClassifier:
    by_text: dict[str, CommentLabels] = field(default_factory=dict)
    version: str = "fake-v1"
    seen: list[tuple[str, str]] = field(default_factory=list)

    def classify(self, pairs: Sequence[tuple[str, str]]) -> list[CommentLabels]:
        self.seen += pairs
        return [self.by_text.get(text, NO_LABEL) for text, _ in pairs]


def _run(
    comments: list[CommentIn],
    llm: FakeLlmClient,
    previous_hash: str | None = None,
    is_llm_killed: bool = False,
    classifier: CommentClassifier | None = None,
) -> SummaryRun:
    return run_summary(
        comments=comments,
        caption="Phòng view biển",
        itinerary=ITINERARY,
        previous_hash=previous_hash,
        now=NOW,
        llm=llm,
        is_llm_killed=is_llm_killed,
        classifier=classifier,
    )


def test_no_comments_never_calls_the_llm() -> None:
    llm = _llm()

    run = _run([], llm)

    assert run.request is not None and run.request.status == "no_comments"
    assert llm.calls == 0


def test_fewer_than_five_people_is_insufficient_and_says_how_many_are_missing() -> None:
    llm = _llm()

    run = _run(_comments(3), llm)

    assert run.request is not None and run.request.status == "insufficient_data"
    assert run.request.content is not None and run.request.content.needed == 2
    assert llm.calls == 0


def test_ready_summary_uses_real_ids_counted_people_and_a_code_built_text() -> None:
    run = _run(_comments(), _llm(pros=PROS))

    request = run.request
    assert request is not None and request.status == "ready"
    assert request.summary == "Khen: View biển đẹp."
    assert request.content is not None
    [point] = request.content.pros
    assert point.people == 3 and all(i.startswith("cmt_") for i in point.comment_ids)
    body = request.model_dump(mode="json", by_alias=True)
    assert {"inputHash", "promptVersion", "commentCount", "generatedAt"} <= set(body)
    assert body["content"]["pros"][0]["commentIds"] == point.comment_ids


def _point(ids: list[str], text: str) -> dict[str, object]:
    return {"comment_ids": ids, "aspect": "canh_quan", "text": text}


def test_short_text_keeps_both_sides_and_puts_the_most_backed_point_first() -> None:
    long_tail = "x" * 110
    pros = [_point(["c1", "c2"], f"Ít người {long_tail}"), _point(["c1", "c2", "c3"], "Phòng đẹp")]
    pros += [_point(["c1", "c2"], f"Khen {i} {long_tail}") for i in range(3)]
    cons = [_point(["c4", "c5"], "Bữa sáng ít món")]

    request = _run(_comments(), _llm(pros=pros, cons=cons)).request

    assert request is not None and request.summary is not None and request.content is not None
    assert len(request.summary) <= MAX_SUMMARY_CHARS
    assert request.summary.startswith("Khen: Phòng đẹp;")  # 3 people beats 2
    assert "Chê: Bữa sáng ít món." in request.summary  # not crowded out by long praise
    assert len(request.content.pros) == 5  # the full list stays in content


def test_same_input_hash_skips_the_llm() -> None:
    first = _run(_comments(), _llm(pros=PROS))
    assert first.request is not None
    llm = _llm(pros=PROS)

    again = _run(_comments(), llm, previous_hash=first.request.input_hash)

    assert again.request is None
    assert llm.calls == 0
    # what core needs to move its staleness mark: the same hash and the post's count
    assert again.checked is not None
    assert again.checked.input_hash == first.request.input_hash
    assert again.checked.comment_count == first.request.comment_count


def test_hiding_a_safety_comment_the_llm_never_saw_still_resaves() -> None:
    """Over a year old (L2), so never sent, yet the only safety hit: hiding it must clear it."""
    old_safety = _comment(7, "Ăn buffet ở đây bị ngộ độc cả nhà").model_copy(
        update={"created_at": NOW - timedelta(days=400)}
    )
    first = _run([*_comments(), old_safety], _llm(pros=PROS))
    assert first.request is not None and first.request.safety is not None
    assert first.request.safety.warnings or first.request.safety.pending_warnings

    assert first.request.content is not None and first.request.content.counts.sent == 5
    hidden = old_safety.model_copy(update={"status": "hidden"})
    again = _run([*_comments(), hidden], _llm(pros=PROS), previous_hash=first.request.input_hash)

    assert again.request is not None and again.request.safety is not None
    assert again.request.safety.warnings == again.request.safety.pending_warnings == []


def test_sources_are_what_reached_the_llm_reply_parents_included() -> None:
    """Core holds a summary back when one of these is hidden, so none may be missing."""
    old_question = _comment(8, "Phòng ở đây có view biển không mọi người ơi").model_copy(
        update={"created_at": NOW - timedelta(days=400)}  # too old to send (L2), still a parent
    )
    reply = _comment(9, "Có nha, mình ở tầng 12 nhìn thẳng ra biển rất đẹp").model_copy(
        update={"parent_id": "cmt_8"}
    )
    run = _run([*_comments(), old_question, reply], _llm(pros=PROS))

    assert run.request is not None and run.request.status == "ready"
    assert run.request.source_comment_ids == sorted(
        [f"cmt_{i}" for i in range(5)] + ["cmt_8", "cmt_9"]
    )


def test_no_comment_text_saved_means_empty_sources_not_unknown() -> None:
    for comments in ([], _comments(3)):
        run = _run(comments, _llm())
        assert run.request is not None and run.request.source_comment_ids == []


def test_output_breaking_the_schema_fails_without_a_hash() -> None:
    run = _run(_comments(), FakeLlmClient('{"pros": "x"}'))

    assert run.request is not None and run.request.status == "failed"
    assert run.request.input_hash is None  # next run tries again


def test_kill_switch_fails_without_calling_the_llm() -> None:
    llm = _llm(pros=PROS)

    run = _run(_comments(), llm, is_llm_killed=True)

    assert run.request is not None and run.request.status == "failed"
    assert llm.calls == 0


def test_no_point_with_two_people_is_not_shown_as_ready() -> None:
    lonely = [{"comment_ids": ["c1"], "aspect": "canh_quan", "text": "View đẹp"}]

    run = _run(_comments(), _llm(pros=lonely))

    assert run.request is not None and run.request.status == "insufficient_data"
    assert run.llm is not None  # the paid call is still reported for cost


def test_only_first_hand_safety_warnings_are_public() -> None:
    comments = [
        *_comments(),
        _comment(7, "Mình ở đây tuần trước, ăn buffet xong bị ngộ độc cả nhà"),
        _comment(8, "Nghe nói chỗ này hay bị ngộ độc lắm"),
    ]

    run = _run(comments, _llm(pros=PROS))

    assert run.request is not None and run.request.safety is not None
    assert [w.comment_ids for w in run.request.safety.warnings] == [["cmt_7"]]


def test_every_status_sends_generated_at_because_core_rejects_null() -> None:
    """Core's Zod schema refuses generatedAt=null and orders writes by it (be PR #58)."""
    runs = [
        _run([], _llm()),  # no_comments
        _run(_comments(3), _llm()),  # insufficient_data before the LLM
        _run(_comments(), _llm(pros=[{"comment_ids": ["c1"], "aspect": "canh_quan", "text": "x"}])),
        _run(_comments(), FakeLlmClient('{"pros": "x"}')),  # failed
        _run(_comments(), _llm(pros=PROS)),  # ready
    ]

    statuses = []
    for run in runs:
        assert run.request is not None
        body = run.request.model_dump(mode="json", by_alias=True)
        assert body["generatedAt"] == NOW.isoformat().replace("+00:00", "Z")
        statuses.append(body["status"])
    assert statuses == ["no_comments", "insufficient_data", "insufficient_data", "failed", "ready"]


def test_classifier_decides_who_went_for_safety_warnings() -> None:
    own = "Mình ở đây tuần trước, ăn buffet xong bị ngộ độc cả nhà"
    heard = "Nghe nói chỗ này hay bị ngộ độc lắm"
    comments = [*_comments(), _comment(7, own), _comment(8, heard)]
    # the opposite of what the rules say, to show the labels win
    classifier = FakeClassifier({own: HEARSAY, heard: FIRST_HAND})

    run = _run(comments, _llm(pros=PROS), classifier=classifier)

    assert run.request is not None and run.request.safety is not None
    assert [w.comment_ids for w in run.request.safety.warnings] == [["cmt_8"]]
    # hearsay goes to core for a moderator; core's public GET leaves it out
    body = run.request.model_dump(mode="json", by_alias=True)
    assert body["safety"]["pendingWarnings"] == [
        {"categories": ["ngo_doc"], "commentIds": ["cmt_7"]}
    ]


def test_classifier_video_reaction_label_never_drops_a_comment() -> None:
    """The label misreads real visits ("cô chủ dễ thương, cho mượn xe đạp free", live eval)."""
    misread = "cô chủ dễ thương, cho mượn xe đạp free"
    comments = [*_comments(), _comment(6, misread)]

    run = _run(comments, _llm(pros=PROS), classifier=FakeClassifier({misread: REACTION}))

    assert run.request is not None and run.request.content is not None
    assert run.request.content.counts.sent == 6


def test_classifier_reads_each_comment_with_its_visible_parent() -> None:
    parent = _comment(5, "Có ai ở đây rồi không, phòng có ồn không?")
    hidden = _comment(9, "Bình luận đã bị ẩn").model_copy(update={"status": "hidden"})
    reply = _comment(6, "Mình ở rồi, yên tĩnh lắm").model_copy(update={"parent_id": "cmt_5"})
    orphan = _comment(7, "Ồn lắm nha, tối không ngủ được").model_copy(update={"parent_id": "cmt_9"})
    classifier = FakeClassifier()

    _run([*_comments(), parent, hidden, reply, orphan], _llm(pros=PROS), classifier=classifier)

    assert (reply.body, parent.body) in classifier.seen
    assert (orphan.body, "") in classifier.seen
    assert all(text != hidden.body for text, _ in classifier.seen)  # hidden: not classified


def test_classifier_version_is_part_of_the_input_hash() -> None:
    runs = [
        _run(_comments(), _llm(pros=PROS), classifier=c)
        for c in (None, FakeClassifier(), FakeClassifier(version="fake-v2"))
    ]

    hashes = {r.request.input_hash for r in runs if r.request}
    assert len(hashes) == 3 and None not in hashes


class BrokenClassifier:
    version = "fake-v1"

    def classify(self, pairs: Sequence[tuple[str, str]]) -> list[CommentLabels]:
        raise RuntimeError("onnxruntime failed")


def test_a_classifier_failing_mid_run_falls_back_to_rules() -> None:
    """The summary still comes out, with the rules' hash, so a healthy classifier redoes it."""
    broken = _run(_comments(), _llm(pros=PROS), classifier=BrokenClassifier())
    rules = _run(_comments(), _llm(pros=PROS))
    healthy = _run(_comments(), _llm(pros=PROS), classifier=FakeClassifier())

    assert broken.request is not None and broken.request.status == "ready"
    assert rules.request is not None and healthy.request is not None
    assert broken.request.input_hash == rules.request.input_hash != healthy.request.input_hash


def test_the_summary_says_who_labelled_the_comments() -> None:
    """A silent fall to rules halves video-gap recall: the saved content must say so."""

    def labeler(run: SummaryRun) -> str:
        assert run.request is not None and run.request.content is not None
        return run.request.content.labeler

    capped = run_summary(
        comments=_comments(),
        caption="Phòng view biển",
        itinerary=ITINERARY,
        previous_hash=None,
        now=NOW,
        llm=_llm(pros=PROS),
        classifier=FakeClassifier(),
        classifier_max_comments=2,  # 5 comments want labels, 2 get them
    )

    assert labeler(_run(_comments(), _llm(pros=PROS))) == "rules"
    assert labeler(_run(_comments(), _llm(pros=PROS), classifier=FakeClassifier())) == "model"
    assert labeler(_run(_comments(), _llm(pros=PROS), classifier=BrokenClassifier())) == "rules"
    assert labeler(capped) == "mixed"
    assert labeler(_run(_comments(3), _llm(), classifier=FakeClassifier())) == "model"


def test_stored_labels_are_reused_and_only_new_ones_come_back() -> None:
    """With labels kept from the label worker, a rerun of a big post classifies only what
    is new, and gets the same hash as labelling everything again."""
    full = FakeClassifier()
    all_labelled = _run(_comments(), _llm(pros=PROS), classifier=full)
    partial = FakeClassifier()
    known = {f"cmt_{i}": NO_LABEL for i in range(3)}

    run = run_summary(
        comments=_comments(),
        caption="Phòng view biển",
        itinerary=ITINERARY,
        previous_hash=None,
        now=NOW,
        llm=_llm(pros=PROS),
        classifier=partial,
        known_labels=known,
    )

    assert [text for text, _ in partial.seen] == [TEXTS[3], TEXTS[4]]
    assert set(run.new_labels) == {"cmt_3", "cmt_4"}
    assert run.request is not None and all_labelled.request is not None
    assert run.request.input_hash == all_labelled.request.input_hash


def test_the_model_is_part_of_the_input_hash() -> None:
    """Switching models must re-summarize: same input, other model, other hash."""
    other = _llm(pros=PROS)
    other.model = "other-model"

    first = _run(_comments(), _llm(pros=PROS)).request
    second = _run(_comments(), other).request

    assert first is not None and second is not None
    assert first.input_hash != second.input_hash


def test_classifier_skips_comments_the_rules_dropped_but_not_safety_hits() -> None:
    """Labels are read only for candidates and safety hits: skipping the rest saves time."""
    spam = _comment(6, "Săn voucher giảm 50% tại shopee.vn/sale nha")  # L6 link
    short_safety = _comment(7, "bị ngộ độc")  # too short for a candidate, still a safety hit
    hidden = _comment(8, "Mình ở 2 đêm, phòng sạch").model_copy(update={"status": "hidden"})
    classifier = FakeClassifier()

    _run([*_comments(), spam, short_safety, hidden], _llm(pros=PROS), classifier=classifier)

    seen = {text for text, _ in classifier.seen}
    assert spam.body not in seen and hidden.body not in seen
    assert short_safety.body in seen
    assert {c.body for c in _comments()} <= seen


def _summary(
    pros: list[SummaryPoint], cons: list[SummaryPoint], gaps: list[RealityGapPoint] | None = None
) -> str:
    return _summary_text(ValidatedSummary(pros, cons, gaps or [], [], (), []))


def _p(
    aspect: str, people: int, text: str, short: str | None = None, ids: str = ""
) -> SummaryPoint:
    comment_ids = tuple(ids.split()) or tuple(f"{aspect}_{i}" for i in range(people))
    return SummaryPoint(aspect, text, comment_ids, people, short)  # type: ignore[arg-type]


def test_short_forms_let_the_text_hold_every_point() -> None:
    """Large post (BAO_CAO): full sentences fit 4 of 10 points in 300 chars."""
    long = "câu đầy đủ rất dài để mô tả ý này cho người đọc hiểu rõ hơn nữa"
    pros = [
        _p(a, 9 - k, f"{a} {long}", f"{a} tốt")
        for k, a in enumerate(["canh_quan", "phuc_vu", "phong_o"])
    ]
    cons = [
        _p(a, 8 - k, f"{a} {long}", f"{a} tệ") for k, a in enumerate(["gia_ca", "do_an", "ve_sinh"])
    ]

    text = _summary(pros, cons)

    assert text == (
        "Khen: canh_quan tốt; phuc_vu tốt; phong_o tốt. Chê: gia_ca tệ; do_an tệ; ve_sinh tệ."
    )


def test_missing_short_falls_back_to_the_sentence() -> None:
    assert _summary([_p("canh_quan", 3, "View biển đẹp.")], []) == "Khen: View biển đẹp."


def test_a_con_resting_on_the_writers_of_a_video_gap_is_left_to_the_gap() -> None:
    cable = _p("dong_duc", 5, "Cáp treo đông", "cáp treo đông", ids="a b c d e")
    price = _p("gia_ca", 3, "Đồ ăn mắc", "đồ ăn mắc", ids="f g h")
    gap = RealityGapPoint(
        "clm_1",
        "Cáp treo không phải chờ",
        "Phải chờ lâu",
        ("a", "b", "c"),
        3,
        "cáp treo phải chờ lâu",
    )

    text = _summary([], [cable, price], [gap])

    assert text == "Chê: đồ ăn mắc. Khác video: cáp treo phải chờ lâu."


def test_the_side_more_people_back_picks_first_when_space_runs_out() -> None:
    filler = "x" * 80  # three items fit, not four
    pros = [_p("canh_quan", 2, f"Khen một {filler}"), _p("phong_o", 2, f"Khen hai {filler}")]
    cons = [_p("gia_ca", 6, f"Chê một {filler}"), _p("do_an", 5, f"Chê hai {filler}")]

    text = _summary(pros, cons)

    assert "Chê một" in text and "Chê hai" in text and "Khen hai" not in text


def test_a_reply_whose_parent_is_outside_the_sample_keeps_it_as_context() -> None:
    """Core's sample brings the parent's text along (PR be #128); its id is a source too."""
    reply = _comment(6, "Mình ở rồi, yên tĩnh lắm, phòng rộng").model_copy(
        update={"parent_id": "cmt_out", "parent_body": "Phòng có ồn không mọi người?"}
    )
    classifier = FakeClassifier()

    run = _run([*_comments(), reply], _llm(pros=PROS), classifier=classifier)

    assert (reply.body, "Phòng có ồn không mọi người?") in classifier.seen
    assert run.request is not None and "cmt_out" in (run.request.source_comment_ids or [])


def test_kept_safety_results_outside_the_sample_reach_the_summary() -> None:
    """Only when the run read a part of the post: core's counts say there is more."""
    inside = _comment(5, "Mình ăn hải sản ở đây xong bị ngộ độc cả nhà")
    kept = [
        StoredSafety("cmt_far", ("ngo_doc",), "public"),
        StoredSafety("cmt_hearsay", ("tai_nan",), "pending_review"),
        StoredSafety("cmt_5", ("ngo_doc",), "public"),  # read this run: its own result wins
    ]

    run = run_summary(
        comments=[*_comments(), inside],
        caption="",
        itinerary=[],
        previous_hash=None,
        now=NOW,
        llm=_llm(pros=PROS),
        known_safety=kept,
        post_stats=PostStats(comments=500, writers=400),  # 6 of 500 read
    )

    assert run.request is not None and run.request.safety is not None
    warnings = [w.comment_ids for w in run.request.safety.warnings]
    pending = [w.comment_ids for w in run.request.safety.pending_warnings]
    assert ["cmt_far"] in warnings and ["cmt_hearsay"] in pending
    assert sum(ids == ["cmt_5"] for ids in warnings + pending) == 1


def test_core_counts_add_the_population_and_an_estimate_when_the_post_is_bigger() -> None:
    def run(stats: PostStats) -> SummaryRun:
        return run_summary(
            comments=_comments(),
            caption="",
            itinerary=[],
            previous_hash=None,
            now=NOW,
            llm=_llm(pros=PROS),
            post_stats=stats,
        )

    whole = run(PostStats(comments=5, writers=5)).request
    big = run(PostStats(comments=5_000, writers=4_000)).request

    assert whole is not None and whole.content is not None
    assert whole.content.population is not None and whole.content.pros[0].estimate is None
    assert big is not None and big.content is not None
    estimate = big.content.pros[0].estimate
    assert estimate is not None and estimate.people == 2_400  # 3 of 5 writers of 4,000


QUESTIONS = [
    "Giá phòng ở đây bao nhiêu vậy mọi người?",
    "Có hồ bơi cho trẻ em không ạ?",
    "Đi tháng mấy thì đẹp nhất vậy?",
    "Từ sân bay về đây bao xa vậy?",
    "Phòng có view biển không mọi người?",
]


def test_five_questions_do_not_pass_the_gate_or_call_the_llm() -> None:
    llm = _llm()

    run = _run([_comment(i, t) for i, t in enumerate(QUESTIONS)], llm)

    assert run.request is not None and run.request.status == "insufficient_data"
    assert run.request.content is not None and run.request.content.needed == 5
    assert llm.calls == 0


def test_a_paid_empty_run_keeps_its_hash_so_the_same_input_is_not_paid_again() -> None:
    """Enough people, no point with 2 of them: the LLM was paid once, never twice."""
    llm = _llm()  # no points at all
    first = _run(_comments(), llm)
    assert first.request is not None and first.request.status == "insufficient_data"
    assert first.request.input_hash is not None

    again = _run(_comments(), llm, previous_hash=first.request.input_hash)

    assert again.request is None and llm.calls == 1


def test_the_comment_count_saved_is_the_whole_posts_not_the_sample() -> None:
    """Core marks a summary stale when the post's count differs from the saved one."""
    run = run_summary(
        comments=_comments(),
        caption="",
        itinerary=[],
        previous_hash=None,
        now=NOW,
        llm=_llm(pros=PROS),
        post_stats=PostStats(comments=9_000, writers=4_000),
    )

    assert run.request is not None and run.request.comment_count == 9_000
    assert _run(_comments(), _llm(pros=PROS)).request.comment_count == 5  # type: ignore[union-attr]


def test_a_whole_read_ignores_kept_safety_results_of_comments_no_longer_there() -> None:
    """Every visible comment was read, so a kept result of a missing one is a hidden comment."""
    kept = [StoredSafety("cmt_hidden", ("ngo_doc",), "public")]

    run = run_summary(
        comments=_comments(),
        caption="",
        itinerary=[],
        previous_hash=None,
        now=NOW,
        llm=_llm(pros=PROS),
        known_safety=kept,
        post_stats=PostStats(comments=5, writers=5),
    )

    assert run.request is not None and run.request.safety is not None
    assert run.request.safety.warnings == [] and run.request.safety.pending_warnings == []


def test_safety_comments_are_not_sent_to_the_llm() -> None:
    """The safety path reports them; as LLM evidence they were always dropped (V5)."""
    sent: list[str] = []

    class Recording(FakeLlmClient):
        def generate(self, system: str, user: str, schema: dict[str, object]) -> LlmResult:
            sent.append(user)
            return super().generate(system, user, schema)

    llm = Recording(_llm(pros=PROS).output)
    poisoned = _comment(6, "Mình ăn hải sản ở đây xong bị ngộ độc cả nhà")

    run = _run([*_comments(), poisoned], llm)

    assert run.request is not None and run.request.safety is not None
    assert [
        w.comment_ids for w in run.request.safety.pending_warnings + run.request.safety.warnings
    ] == [["cmt_6"]]
    assert sent and "ngộ độc" not in sent[0]


def test_a_run_whose_llm_fails_still_keeps_its_new_labels() -> None:
    kept: list[dict[str, CommentLabels]] = []

    class DownLlm(FakeLlmClient):
        def generate(self, system: str, user: str, schema: dict[str, object]) -> LlmResult:
            raise LlmUnavailableError(300)

    try:
        run_summary(
            comments=_comments(),
            caption="",
            itinerary=[],
            previous_hash=None,
            now=NOW,
            llm=DownLlm(),
            classifier=FakeClassifier(),
            keep_labels=lambda labels: kept.append(dict(labels)),
        )
    except LlmUnavailableError:
        pass

    assert len(kept) == 1 and len(kept[0]) == 5


def test_a_part_rules_run_hashes_apart_from_a_model_run() -> None:
    """A classifier failing mid-run with stored labels: the next healthy run re-summarizes."""

    class Broken(FakeClassifier):
        def classify(self, pairs: Sequence[tuple[str, str]]) -> list[CommentLabels]:
            raise RuntimeError("onnx")

    def hashed(classifier: CommentClassifier, known: dict[str, CommentLabels]) -> str | None:
        run = run_summary(
            comments=_comments(),
            caption="",
            itinerary=[],
            previous_hash=None,
            now=NOW,
            llm=_llm(pros=PROS),
            classifier=classifier,
            known_labels=known,
        )
        assert run.request is not None
        return run.request.input_hash

    some = {"cmt_0": NO_LABEL}
    assert hashed(Broken(), some) != hashed(FakeClassifier(), some)
