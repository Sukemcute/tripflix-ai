import json
from pathlib import Path

import pytest

from app.services.summary.injection import match_injection
from app.services.summary.vi_text import clean_text

EVAL = Path(__file__).resolve().parents[2] / "evals" / "summary" / "injection_10.jsonl"
CASES = [json.loads(line) for line in EVAL.read_text(encoding="utf-8").splitlines()]
ENGLAND_FLAG = "\U0001f3f4\U000e0067\U000e0062\U000e0065\U000e006e\U000e0067\U000e007f"


def test_eval_set_has_10_cases() -> None:
    assert len(CASES) == 10


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_injection_is_caught(case: dict[str, str]) -> None:
    assert match_injection(case["text"])


def test_hidden_tag_text_never_reaches_the_llm() -> None:
    smuggled = next(c["text"] for c in CASES if c["id"] == "i08")

    assert match_injection(smuggled) == ["hidden_text"]
    assert clean_text(smuggled) == "Phòng ổn previous instructions"


@pytest.mark.parametrize(
    "text",
    [
        "Bỏ qua bữa sáng cũng được vì gần chợ",
        "Ai ơi cho hỏi giá phòng",
        "Từ giờ mình sẽ quay lại mỗi năm",
        "Hãy đi vào mùa hè, biển đẹp nhất",
        f"Đi Anh về nhớ resort này {ENGLAND_FLAG}",  # flag emoji uses tag chars legitimately
        "Phòng <đẹp> lắm, giá 1tr2",
    ],
)
def test_normal_comment_is_clean(text: str) -> None:
    assert match_injection(text) == []
