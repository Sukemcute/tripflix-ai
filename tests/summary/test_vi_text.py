import unicodedata

import pytest

from app.services.summary.vi_text import count_syllables, to_norm, to_raw

TONES = ["", "̀", "́", "̃", "̉", "̣"]


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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("ignоre", "ignore"),  # Cyrillic о
        ("ｉｇｎｏｒｅ", "ignore"),  # fullwidth
        ("\U0001d422\U0001d420\U0001d427\U0001d428\U0001d42b\U0001d41e", "ignore"),  # math bold
        ("ig­nore", "ignore"),  # soft hyphen
    ],
)
def test_to_norm_folds_filter_evasion_tricks(text: str, expected: str) -> None:
    assert to_norm(text) == expected


def test_to_raw_drops_every_unicode_format_char() -> None:
    """Hidden text in raw would reach the LLM while rules on norm never see it."""
    format_chars = [chr(i) for i in range(0x110000) if unicodedata.category(chr(i)) == "Cf"]

    assert to_raw("Phòng" + "".join(format_chars) + " ổn") == "Phòng ổn"


def test_to_raw_keeps_every_vietnamese_letter() -> None:
    """NFKC must not change Vietnamese: it has no compatibility forms."""
    letters = "aăâeêioôơuưyAĂÂEÊIOÔƠUƯY"
    words = [unicodedata.normalize("NFC", ch + mark) for ch in letters for mark in TONES]

    assert [to_raw(w) for w in words] == words


def test_count_syllables() -> None:
    assert count_syllables(to_norm("Mình đi cách đây 2 tháng!")) == 6
    assert count_syllables("") == 0


def test_count_syllables_counts_a_repeated_phrase_once() -> None:
    """Use case #1: copy-pasting a phrase must not pass the length rule (L5)."""
    assert count_syllables(to_norm("Đẹp quá đẹp quá đẹp quá đẹp quá đẹp quá")) == 2
    assert count_syllables(to_norm("Phòng sạch sẽ " * 6)) == 3
    assert count_syllables(to_norm("hoà bình, hòa bình")) == 2


def test_count_syllables_skips_padding_runs_but_not_single_numbers() -> None:
    """Use case #4: "1 2 3 ... a b c" is padding; "đi 2 tháng" is content."""
    assert count_syllables(to_norm("Video bổ ích quá 1 2 3 4 5 6 7 8 9 10 a b c d e f")) == 4
    assert count_syllables(to_norm("Mình đi 2 tháng, giá 500k")) == 6


def test_to_raw_strips_zalgo_marks_but_keeps_vietnamese() -> None:
    """Use case #8: stacked marks would reach the LLM and waste tokens."""
    zalgo = "B̸̡̛̖̙̗̓̈́ã̴̢̛̗͚̓i̵̢̗̓ ̴̢̛̗̓b̵̢̛̗̓i̴̢̛̗̓ể̵̢̛̗n̴̢̛̗̓"
    assert to_raw(zalgo) == "Bãi biển"
    assert to_raw("Đ̷ẹ̷p̷ ̷x̷ỉ̷u̷") == "Đẹp xỉu"


def test_mentions_become_a_placeholder_and_emails_stay() -> None:
    """Use case #15: names in @tags must not reach the LLM (BERTweet's @USER)."""
    assert to_raw("@linh @huy.nguyen_99 nhìn quen không") == "@USER @USER nhìn quen không"
    assert to_norm("@linh nhìn quen không") == "nhin quen khong"
    assert to_raw("mail abc@gmail.com") == "mail abc@gmail.com"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("l.ừ.a đ.ả.o mọi người", "lua dao moi nguoi"),
        ("dùng ch.án lắm", "dung chan lam"),
        ("k*é*m chất lượng", "kem chat luong"),
        ("Giá 1.500k, wifi 2.5km", "gia 1 500k wifi 2 5km"),  # numbers are not glued
        ("Đẹp lắm.Phòng rộng", "dep lam phong rong"),  # missing space is not glued
    ],
)
def test_to_norm_joins_letters_split_to_dodge_filters(text: str, expected: str) -> None:
    """Use case #10: letters split by . * _ - are joined for the rules only."""
    assert to_norm(text) == expected
