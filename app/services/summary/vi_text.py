"""Vietnamese comment text in two forms: raw (sent to the LLM) and norm (for rules and matching)."""

import re
import unicodedata
from functools import lru_cache

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
# Every Vietnamese letter has a precomposed form, so after NFKC a combining mark that is
# left is Zalgo or strike-through. UAX #15 caps runs at 30 marks, too loose for this
# (Zalgo uses ~5 per letter): proposed by Claude from Vietnamese spelling (BAO_CAO use cases).
_LEFTOVER_MARKS = re.compile("[̀-ͯ҃-҉᪰-᫿᷀-᷿⃐-⃿︠-︯]")
# @mentions become one placeholder (BERTweet's @USER) so names never reach the LLM
# (Google Maps bans naming people). The lookbehind keeps emails ("a@b.com") intact.
MENTION = "@USER"
_MENTION = re.compile(r"(?<![\w@])@\w(?:[\w.]*\w)?")
# "l.ừ.a đ.ả.o", "ch.án": letters split by . * _ - to dodge keyword filters (Gröndahl
# et al. 2018). Joined in norm only, like Meta's text normalizer; raw keeps what was typed.
# shortcut: pieces of 1-2 letters only, so "đẹp.Phòng" (missing space) is not glued.
_LETTER = r"[^\W\d_]"
_SPLIT_WORD = re.compile(rf"(?<!\w){_LETTER}{{1,2}}(?:[.*_\-]{_LETTER}{{1,2}})+(?!\w)")
_SPLITTERS = re.compile(r"[.*_\-]")
_PADDING_TOKEN = re.compile(r"^(?:\w|\d+)$")  # one char or a bare number: "1 2 3 a b c"
MAX_REPEAT_NGRAM = 10  # Gopher measures duplicate n-grams up to n = 10
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


# Filters, safety and injection each normalize the same body: cache the pure functions.
# 2048 entries x 2 caches x 2k chars max is ~8 MB worst case, ~2 MB for typical comments.
@lru_cache(maxsize=2048)
def clean_text(text: str) -> str:
    """NFKC, no format chars, single spaces. Keeps diacritics and emoji for the LLM.

    NFKC (not NFC) also folds fullwidth and math letters ("ｉｇｎｏｒｅ", "𝐢𝐠𝐧𝐨𝐫𝐞")
    to ASCII; Vietnamese letters have no compatibility forms, so they come out as NFC.
    """
    text = _FORMAT_CHARS.sub("", unicodedata.normalize("NFKC", text))
    text = _MENTION.sub(MENTION, _LEFTOVER_MARKS.sub("", text))
    return _SPACES.sub(" ", text).strip()


@lru_cache(maxsize=2048)
def normalize_text(text: str) -> str:
    """Lowercase ASCII words for regex rules: no diacritics, emoji or punctuation.

    Tone-mark placement ("hoà" vs "hòa") needs no handling: both fold to "hoa".
    Runs of 3+ identical chars collapse to one ("quáaaa" -> "qua"); real double
    letters such as "xoong" are kept.
    """
    text = clean_text(text).replace(MENTION, " ").lower().translate(_FOLD_LETTERS)
    text = _SPLIT_WORD.sub(lambda m: _SPLITTERS.sub("", m.group()), text)
    text = _COMBINING_MARKS.sub("", unicodedata.normalize("NFD", text))
    text = _REPEATS.sub(r"\1", _NON_WORD.sub(" ", text))
    return _SPACES.sub(" ", text).strip()


def count_syllables(text_norm: str) -> int:
    """Syllables that carry content (Vietnamese writes one syllable per token).

    A phrase repeated back to back counts once ("dep qua dep qua dep qua" -> 2), the idea
    behind Gopher's duplicate n-gram filter (Rae et al. 2021) applied to one comment.
    A run of 3+ one-char or number tokens is padding ("1 2 3 4 a b c") and counts 0.
    """
    tokens = text_norm.split()
    keep = [True] * len(tokens)
    start = 0
    for i in range(len(tokens) + 1):
        if i < len(tokens) and _PADDING_TOKEN.match(tokens[i]):
            continue
        if i - start >= 3:
            keep[start:i] = [False] * (i - start)
        start = i + 1
    tokens = [t for t, k in zip(tokens, keep, strict=True) if k]

    i = 0
    while i < len(tokens):
        for n in range(min(MAX_REPEAT_NGRAM, (len(tokens) - i) // 2), 0, -1):
            if tokens[i] == tokens[i + n] and tokens[i : i + n] == tokens[i + n : i + 2 * n]:
                del tokens[i + n : i + 2 * n]
                break
        else:
            i += 1
    return len(tokens)
