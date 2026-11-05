from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from app.services.summary.pipeline import SummaryRun
from app.services.summary.schemas import (
    SafetyWarning,
    SaveSummaryRequest,
    SummaryContent,
    SummaryCounts,
    SummaryPointOut,
    SummarySafety,
)
from evals.run_evals import GATES, load_seed, score_post, summarize

SEED = {p["post_id"]: p for p in load_seed()}
COUNTS = SummaryCounts(comments=9, people=6, sent=6)


def _ready(
    post: dict[str, Any], points: list[SummaryPointOut], warnings: Sequence[SafetyWarning] = ()
) -> SummaryRun:
    content = SummaryContent(pros=points, counts=COUNTS)
    request = SaveSummaryRequest(
        status="ready",
        summary="x",
        content=content,
        safety=SummarySafety(warnings=list(warnings)),
        comment_count=len(post["comments"]),
        generated_at=datetime(2026, 11, 5, tzinfo=UTC),
    )
    return SummaryRun(request)


def _point(ids: list[str], aspect: str = "canh_quan", text: str = "Cảnh đẹp.") -> SummaryPointOut:
    return SummaryPointOut(aspect=aspect, text=text, comment_ids=ids, people=len(ids))  # type: ignore[arg-type]


def test_a_matching_point_is_found_and_all_gates_pass() -> None:
    post = SEED["s15-injection"]

    result = score_post(post, _ready(post, [_point(["s15-c04", "s15-c05"])]), 1.0)

    assert all(result.gates.values()), result.gates
    assert (result.points_found, result.points_correct) == (1, 1)


def test_citing_an_injection_comment_fails_the_gate() -> None:
    post = SEED["s15-injection"]

    result = score_post(post, _ready(post, [_point(["s15-c01", "s15-c04"])]), 1.0)

    assert result.gates["no_injection_cited"] is False
    assert result.wrongly_cited == ["s15-c01"]


def test_a_missing_public_safety_warning_fails_the_gate() -> None:
    post = SEED["s08-ngo-doc"]

    missed = score_post(post, _ready(post, []), 1.0)
    warned = [SafetyWarning(categories=["ngo_doc"], comment_ids=["s08-c01"])]
    caught = score_post(post, _ready(post, [], warned), 1.0)

    assert missed.gates["no_safety_miss"] is False
    assert caught.gates["no_safety_miss"] is True


def test_a_number_written_by_the_llm_fails_the_gate() -> None:
    post = SEED["s15-injection"]
    point = _point(["s15-c04", "s15-c05"], text="Nhiều người khen cảnh đẹp.")

    assert score_post(post, _ready(post, [point]), 1.0).gates["no_llm_numbers"] is False


def test_summary_counts_gates_and_scores() -> None:
    post = SEED["s15-injection"]
    results = [score_post(post, _ready(post, [_point(["s15-c04", "s15-c05"])]), 2.0)]

    report = summarize(results)

    assert set(report["gates_passed"]) == set(GATES)
    assert report["all_gates_pass"] is True
    assert report["point_recall"] == round(1 / 3, 3)
