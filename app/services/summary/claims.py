"""Claims the video makes, clm_1..clm_K, for the "Video và thực tế" check (QT Bước 10).

Each itinerary item of kind "service" is one claim. The caption is split into sentences,
then into clauses (commas, semicolons, dashes, bars, emoji between words): one claim per
checkable statement, so "buffet hơn 100 món, cáp treo không phải chờ" is two claims a
comment can contradict one at a time (atomic facts, FActScore, Min et al. 2023; claim
normalization of social posts, Sundriyal et al. 2023). Those use an LLM; this rule split is
the fallback (proposal by Claude, [CẦN NC] for short Vietnamese captions, QT §10).
A clause under MIN_CLAUSE_SYLLABLES joins the one before ("Đẹp, rẻ, gần biển" stays whole);
a clause that is only hashtags or emoji is dropped.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.services.summary.injection import match_injection
from app.services.summary.schemas import ItineraryItemIn
from app.services.summary.vi_text import clean_text, count_syllables, normalize_text

_SENTENCE_END = re.compile(r"[.!?…\n]+")
# shortcut: emoji blocks only (pictographs, symbols, dingbats), not every Unicode symbol.
# Built from code points: the formatter turns escapes into invisible characters.
_EMOJI_BLOCKS = ((0x1F000, 0x1FAFF), (0x2600, 0x27BF), (0x2B00, 0x2BFF))
_EMOJI = "[" + "".join(f"{chr(a)}-{chr(b)}" for a, b in _EMOJI_BLOCKS) + "]"
_EMOJI_JOINERS = f"[{chr(0xFE0F)}{chr(0x200D)}]?"  # variation selector, zero-width joiner
_CLAUSE_BREAK = re.compile(rf"[,;]|\s[-–—|]\s|{_EMOJI}{_EMOJI_JOINERS}")
_HASHTAG = re.compile(r"#\w+")
MIN_CLAUSE_SYLLABLES = 3  # proposal by Claude: "ăn no", "rẻ" alone say nothing checkable
MAX_CLAIMS = 8  # bounds the prompt for long captions


@dataclass(frozen=True)
class Claim:
    id: str
    text: str
    source: Literal["itinerary", "caption"]


def build_claims(caption: str, itinerary: Sequence[ItineraryItemIn]) -> list[Claim]:
    texts: list[tuple[str, Literal["itinerary", "caption"]]] = [
        (_service_claim(item), "itinerary") for item in itinerary if item.kind == "service"
    ]
    # split before clean_text: it folds newlines into spaces and would lose line breaks
    for sentence in _SENTENCE_END.split(caption):
        texts.extend((clause, "caption") for clause in _clauses(sentence))
    # The creator writes caption and itinerary: untrusted remote content too (OWASP).
    texts = [(t, s) for t, s in texts if not match_injection(t)]
    return [
        Claim(id=f"clm_{i}", text=t, source=s)
        for i, (t, s) in enumerate(texts[:MAX_CLAIMS], start=1)
    ]


def _clauses(sentence: str) -> list[str]:
    clauses: list[str] = []
    short = ""  # a too-short clause waiting for a neighbour
    for part in _CLAUSE_BREAK.split(sentence):
        text = clean_text(_HASHTAG.sub(" ", part))
        if not normalize_text(text):
            continue
        text = f"{short}, {text}" if short else text
        short = ""
        if count_syllables(normalize_text(text)) >= MIN_CLAUSE_SYLLABLES:
            clauses.append(text)
        elif clauses:
            clauses[-1] = f"{clauses[-1]}, {text}"
        else:
            short = text
    if short:
        clauses.append(short)
    return clauses


def _service_claim(item: ItineraryItemIn) -> str:
    return f"{item.service_type}: {item.place_name}" if item.service_type else item.place_name
