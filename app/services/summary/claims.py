"""Claims the video makes, clm_1..clm_K, for the "Video và thực tế" check (QT Bước 10).

Each itinerary item of kind "service" is one claim. The caption is split into sentences;
a sentence that is only hashtags or emoji is dropped. Extracting claims from short
Vietnamese captions has no source yet ([CẦN NC], QT §10), so this is the rule fallback.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from app.services.summary.injection import match_injection
from app.services.summary.schemas import ItineraryItemIn
from app.services.summary.vi_text import clean_text, normalize_text

_SENTENCE_END = re.compile(r"[.!?…\n]+")
_HASHTAG = re.compile(r"#\w+")


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
    for part in _SENTENCE_END.split(caption):
        sentence = clean_text(part)
        if normalize_text(_HASHTAG.sub(" ", sentence)):
            texts.append((sentence, "caption"))
    # The creator writes caption and itinerary: untrusted remote content too (OWASP).
    texts = [(t, s) for t, s in texts if not match_injection(t)]
    return [Claim(id=f"clm_{i}", text=t, source=s) for i, (t, s) in enumerate(texts, start=1)]


def _service_claim(item: ItineraryItemIn) -> str:
    return f"{item.service_type}: {item.place_name}" if item.service_type else item.place_name
