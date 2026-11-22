import json
from pathlib import Path

import pytest

from app.services.summary.safety import match_safety

EVAL = Path(__file__).resolve().parents[2] / "evals" / "summary" / "safety_30.jsonl"
CASES = [json.loads(line) for line in EVAL.read_text(encoding="utf-8").splitlines()]


def test_eval_set_has_30_cases() -> None:
    assert len(CASES) == 30


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_safety_recall_on_eval_set(case: dict[str, str]) -> None:
    """Missing a safety complaint is the worst failure (target 0, QT Bước 7)."""
    hit = match_safety(case["text"])

    assert hit is not None
    assert case["category"] in hit.categories
    assert hit.visibility == case["visibility"]


SEED_DIR = EVAL.parent / "seed"
SEED_SAFETY = [
    (c["body"], label)
    for path in sorted(SEED_DIR.glob("*.json"))
    for post in [json.loads(path.read_text(encoding="utf-8"))]
    for c in post["comments"]
    for label in post["labels"]["safety"]
    if label["comment_id"] == c["comment_id"]
]
SEED_NOT_SAFETY = [
    c["body"]
    for path in sorted(SEED_DIR.glob("*.json"))
    for post in [json.loads(path.read_text(encoding="utf-8"))]
    for c in post["comments"]
    if c["comment_id"] in post["labels"]["not_safety"]
]


@pytest.mark.parametrize(("body", "label"), SEED_SAFETY)
def test_no_safety_miss_on_seed_posts(body: str, label: dict[str, str]) -> None:
    """P12 hard gate "0 missed safety" on the labelled seed (snatch theft, "tối qua" first-hand)."""
    hit = match_safety(body)

    assert hit is not None
    assert label["category"] in hit.categories
    assert hit.visibility == label["visibility"]


@pytest.mark.parametrize("body", SEED_NOT_SAFETY)
def test_negated_safety_words_on_seed_posts_are_not_flagged(body: str) -> None:
    assert match_safety(body) is None


def test_hearsay_waits_for_a_moderator() -> None:
    hit = match_safety("nghe đồn chỗ này hay bị ngộ độc")

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
    assert match_safety(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Không có gián như mọi người đồn đâu",
        "Cả nhà không bị ngộ độc gì cả",
        "Ở 3 đêm chưa từng thấy chuột",
    ],
)
def test_negated_mention_is_not_a_safety_hit(text: str) -> None:
    """NegEx: an existence negation up to 5 tokens before the hit cancels it."""
    assert match_safety(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "Ăn không ngon, bị tào tháo rượt cả đêm",
        "ăn không ngon bị tào tháo rượt cả đêm",  # "khong ngon" is not an existence negation
        "Không có nước nóng, có gián trong phòng",  # a comma ends the negation scope
        "Không những bẩn mà còn có gián",  # pseudo-negation
        "Phòng sạch lắm, có cả gián bò ra chào khách",  # v4: one filler word allowed
        "l.ừ.a đ.ả.o khách",  # use case #10
    ],
)
def test_real_complaint_survives_negation_handling(text: str) -> None:
    assert match_safety(text) is not None
