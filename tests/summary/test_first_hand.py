import pytest

from app.services.summary.first_hand import detect_first_hand
from app.services.summary.vi_text import to_norm


@pytest.mark.parametrize(
    ("comment", "expected"),
    [
        ("Mình đi cách đây 2 tháng, nước biển không sạch lắm", True),
        ("Năm ngoái tụi mình ở đây, phòng nhỏ xíu", True),
        ("Đi rồi, nước biển bẩn, 500k một đêm", True),  # no pronoun: Vietnamese drops the subject
        ("Tôi đã ở tầng 12, view đẹp", True),
        ("Nhìn có vẻ đẹp ghê", False),
        ("Ước được đi 1 lần", False),
        ("Mình chưa đi bao giờ, tháng sau sẽ đi", False),
        ("Tháng trước mình định đi mà huỷ", False),
        ("Nghe nói tháng trước ở đây bị mất nước", False),
        ("Đi tới đây vào buổi tối thì đẹp lắm", False),  # toi = tới/tối, not tôi
        ("Mình thấy phòng đẹp", False),  # first person but no past event
    ],
)
def test_detect_first_hand(comment: str, expected: bool) -> None:
    assert detect_first_hand(to_norm(comment)).is_first_hand is expected


def test_cues_explain_the_decision() -> None:
    result = detect_first_hand(to_norm("Mình chưa đi bao giờ"))

    assert result.cues == ("first_person", "not_experienced")
