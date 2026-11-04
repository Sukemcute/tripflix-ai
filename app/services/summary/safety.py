"""Safety path (QT Bước 7): regex on text_norm, independent of the LLM.

A writer telling their own visit makes the warning public; anything else, hearsay
included ("nghe don cho nay hay bi ngo doc"), waits for a moderator so one fake
comment cannot sink a place. Default proposed by Claude, pending mentor (PRD Q2).
"""

from dataclasses import dataclass
from typing import Literal

from app.services.summary.first_hand import detect_first_hand
from app.services.summary.lexicon import load


@dataclass(frozen=True)
class SafetyHit:
    categories: tuple[str, ...]
    visibility: Literal["public", "pending_review"]


def match_safety(text_norm: str) -> SafetyHit | None:
    categories = load("safety").matches(text_norm)
    if not categories:
        return None
    first_hand = detect_first_hand(text_norm).is_first_hand
    return SafetyHit(
        categories=tuple(categories),
        visibility="public" if first_hand else "pending_review",
    )
