import json
from pathlib import Path

import pytest

from app.services.summary.safety import match_safety
from app.services.summary.vi_text import to_norm

EVAL = Path(__file__).resolve().parents[2] / "evals" / "summary" / "safety_30.jsonl"
CASES = [json.loads(line) for line in EVAL.read_text(encoding="utf-8").splitlines()]


def test_eval_set_has_30_cases() -> None:
    assert len(CASES) == 30


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_safety_recall_on_eval_set(case: dict[str, str]) -> None:
    """Missing a safety complaint is the worst failure (target 0, QT Bước 7)."""
    hit = match_safety(to_norm(case["text"]))

    assert hit is not None
    assert case["category"] in hit.categories
    assert hit.visibility == case["visibility"]


def test_hearsay_waits_for_a_moderator() -> None:
    hit = match_safety(to_norm("nghe đồn chỗ này hay bị ngộ độc"))

    assert hit is not None
    assert hit.visibility == "pending_review"


@pytest.mark.parametrize(
    "text",
    [
        "Clip hài quá cười đau bụng luôn",
        "Đẹp chết đi được 😍",
        "Nón lá ở chợ đẹp lắm",
        "Camera quay đẹp quá ad",
        "Mất cả buổi sáng để check in",
        "Năm nay Mộc Châu đẹp",
        "Mình đi tháng trước, hồ bơi rộng, view biển",
    ],
)
def test_figurative_or_harmless_text_is_not_a_safety_hit(text: str) -> None:
    assert match_safety(to_norm(text)) is None
