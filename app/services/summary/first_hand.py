"""Detect comments where the writer tells their own visit (supporting signal, never a gate).

Rule (BAO_CAO P4 §2.3): not blocked AND past event AND (first person OR concrete detail).
First person alone is weak: it is a top cue of fake reviews (Ott et al. 2011), and
Vietnamese often drops the subject ("di roi, 500k mot dem").
"""

from dataclasses import dataclass

from app.services.summary.lexicon import load


@dataclass(frozen=True)
class FirstHand:
    is_first_hand: bool
    cues: tuple[str, ...]


def detect_first_hand(text_norm: str) -> FirstHand:
    cues = load("first_hand_cues").matches(text_norm)
    found = set(cues)
    is_first_hand = (
        "not_experienced" not in found
        and "past_event" in found
        and bool(found & {"first_person", "concrete_detail"})
    )
    return FirstHand(is_first_hand=is_first_hand, cues=tuple(cues))
