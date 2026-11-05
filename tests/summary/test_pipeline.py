import json
from datetime import UTC, datetime, timedelta

from app.clients.llm.fake import FakeLlmClient
from app.services.summary.pipeline import SummaryRun, run_summary
from app.services.summary.schemas import CommentIn, ItineraryItemIn

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


def _run(
    comments: list[CommentIn], llm: FakeLlmClient, previous_hash: str | None = None, **kw: bool
) -> SummaryRun:
    return run_summary(
        comments=comments,
        caption="Phòng view biển",
        itinerary=ITINERARY,
        previous_hash=previous_hash,
        now=NOW,
        llm=llm,
        **kw,
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


def test_same_input_hash_skips_the_llm() -> None:
    first = _run(_comments(), _llm(pros=PROS))
    assert first.request is not None
    llm = _llm(pros=PROS)

    again = _run(_comments(), llm, previous_hash=first.request.input_hash)

    assert again.request is None
    assert llm.calls == 0


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
