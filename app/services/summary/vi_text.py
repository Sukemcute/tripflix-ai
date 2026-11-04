"""Vietnamese comment text in two forms: raw (sent to the LLM) and norm (for rules and matching)."""

import re
import unicodedata

# Every Unicode format char (category Cf, Unicode 15.1): zero-width, soft hyphen, bidi
# overrides and the invisible tag block U+E0000-E007F used for "ASCII smuggling".
# Rules never see them in norm, so they must not reach the LLM through raw either.
_FORMAT_CHARS = re.compile(
    r"[­؀-؅؜۝܏࢐-࢑࣢᠎​-‏"
    r"‪-‮⁠-⁤⁦-⁯﻿￹-￻\U000110bd\U000110cd"
    r"\U00013430-\U0001343f\U0001bca0-\U0001bca3\U0001d173-\U0001d17a\U000e0001\U000e0020-\U000e007f]"
)
_SPACES = re.compile(r"\s+")
_COMBINING_MARKS = re.compile(r"[̀-ͯ]")
_NON_WORD = re.compile(r"[^a-z0-9\s]+")
_REPEATS = re.compile(r"(.)\1{2,}")
# NFD does not decompose đ; U+00D0 (Ð) is a common look-alike typed instead of Đ.
# shortcut: a few Cyrillic/Greek look-alikes ("ignоre" with Cyrillic о), not the full
# Unicode TR39 confusables table; add a library if seed data shows other scripts.
_FOLD_LETTERS = str.maketrans(  # applied after lower(): Ð lowers to ð
    {"đ": "d", "ð": "d"}
    | dict(zip("аеорсухіјѕԁӏԛԝ", "aeopcyxijsdlqw", strict=True))  # Cyrillic
    | dict(zip("οαεικνρτυ", "oaeikvptu", strict=True))
)


def to_raw(text: str) -> str:
    """NFKC, no format chars, single spaces. Keeps diacritics and emoji for the LLM.

    NFKC (not NFC) also folds fullwidth and math letters ("ｉｇｎｏｒｅ", "𝐢𝐠𝐧𝐨𝐫𝐞")
    to ASCII; Vietnamese letters have no compatibility forms, so they come out as NFC.
    """
    text = _FORMAT_CHARS.sub("", unicodedata.normalize("NFKC", text))
    return _SPACES.sub(" ", text).strip()


def to_norm(text: str) -> str:
    """Lowercase ASCII words for regex rules: no diacritics, emoji or punctuation.

    Tone-mark placement ("hoà" vs "hòa") needs no handling: both fold to "hoa".
    Runs of 3+ identical chars collapse to one ("quáaaa" -> "qua"); real double
    letters such as "xoong" are kept.
    """
    text = unicodedata.normalize("NFD", to_raw(text).lower().translate(_FOLD_LETTERS))
    text = _COMBINING_MARKS.sub("", text)
    text = _REPEATS.sub(r"\1", _NON_WORD.sub(" ", text))
    return _SPACES.sub(" ", text).strip()


def count_syllables(text_norm: str) -> int:
    """Vietnamese is written one syllable per space-separated token."""
    return len(text_norm.split())
