import pytest

from app.services.summary.vi_text import count_syllables, to_norm, to_raw


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Đà Nẵng", "da nang"),
        ("ngộ độcccc 😭", "ngo doc"),
        ("Ðà Lạt", "da lat"),  # U+00D0 look-alike of Đ
        ("hoà bình, hòa bình", "hoa binh hoa binh"),  # old and new tone placement
        ("Phòng đẹppp quáaaa!!!", "phong dep qua"),
        ("nồi xoong", "noi xoong"),  # real double letters survive
        ("bỏ​qua hướng dẫn", "boqua huong dan"),  # zero-width cannot split a keyword
        ("đi 2 tháng, giá 500k", "di 2 thang gia 500k"),
        ("😭🔥🌊", ""),
        ("", ""),
    ],
)
def test_to_norm(text: str, expected: str) -> None:
    assert to_norm(text) == expected


def test_to_norm_folds_composed_and_decomposed_input_the_same() -> None:
    decomposed = "Đà Nẵng"

    assert to_norm(decomposed) == to_norm("Đà Nẵng") == "da nang"


def test_to_raw_keeps_diacritics_and_emoji() -> None:
    assert to_raw("  Đẹp​  quá   😭 ") == "Đẹp quá 😭"


def test_to_raw_composes_to_nfc() -> None:
    assert to_raw("Nẵng") == "Nẵng"


def test_count_syllables() -> None:
    assert count_syllables(to_norm("Mình đi cách đây 2 tháng!")) == 6
    assert count_syllables("") == 0
