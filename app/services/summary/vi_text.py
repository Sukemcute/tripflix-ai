"""Vietnamese comment text in two forms: raw (sent to the LLM) and norm (for rules and matching)."""

import re
import unicodedata

_ZERO_WIDTH = re.compile(r"[​-‍⁠﻿]")
_SPACES = re.compile(r"\s+")
_COMBINING_MARKS = re.compile(r"[̀-ͯ]")
_NON_WORD = re.compile(r"[^a-z0-9\s]+")
_REPEATS = re.compile(r"(.)\1{2,}")
# NFD does not decompose đ; U+00D0 (Ð) is a common look-alike typed instead of Đ.
_D_LETTERS = str.maketrans({"đ": "d", "Đ": "D", "Ð": "D"})


def to_raw(text: str) -> str:
    """NFC, no zero-width chars, single spaces. Keeps diacritics and emoji for the LLM."""
    text = _ZERO_WIDTH.sub("", unicodedata.normalize("NFC", text))
    return _SPACES.sub(" ", text).strip()


def to_norm(text: str) -> str:
    """Lowercase ASCII words for regex rules: no diacritics, emoji or punctuation.

    Tone-mark placement ("hoà" vs "hòa") needs no handling: both fold to "hoa".
    Runs of 3+ identical chars collapse to one ("quáaaa" -> "qua"); real double
    letters such as "xoong" are kept.
    """
    text = unicodedata.normalize("NFD", to_raw(text).translate(_D_LETTERS).lower())
    text = _COMBINING_MARKS.sub("", text)
    text = _REPEATS.sub(r"\1", _NON_WORD.sub(" ", text))
    return _SPACES.sub(" ", text).strip()


def count_syllables(text_norm: str) -> int:
    """Vietnamese is written one syllable per space-separated token."""
    return len(text_norm.split())
