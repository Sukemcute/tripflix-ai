import pytest

from app.services.summary import complaint_model
from app.services.summary.complaint_model import _char_ngrams, is_complaint, predict_probability


def test_model_file_loads_with_both_feature_blocks() -> None:
    model = complaint_model.load()

    assert model.version >= 1
    assert len(model.word) > 1_000 and len(model.char) > 1_000
    assert 0 < model.threshold < 1


@pytest.mark.parametrize(
    "text",
    [
        "mình ở rồi, phòng bẩn vl",
        "phòng ẩm mốc hôi kinh khủng",
        "Phòng rất bẩn và nhân viên thô lỗ. Tôi sẽ không quay lại.",
    ],
)
def test_clear_complaints_are_flagged(text: str) -> None:
    assert is_complaint(text)


@pytest.mark.parametrize(
    "text",
    ["Phòng sạch, nhân viên dễ thương", "Resort nằm gần biển, nhìn khá rộng", ""],
)
def test_praise_and_neutral_are_not(text: str) -> None:
    assert not is_complaint(text)
    assert 0 <= predict_probability(text) < 0.5


def test_char_ngrams_follow_scikit_learn_char_wb() -> None:
    """Short words count once and stop, like TfidfVectorizer(analyzer="char_wb")."""
    assert list(_char_ngrams("ab")) == [" a", "ab", "b ", " ab", "ab ", " ab "]
    assert list(_char_ngrams("a")) == [" a", "a ", " a "]
