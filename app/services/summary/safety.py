"""Safety path (QT Bước 7): regex on text_norm, independent of the LLM.

A writer telling their own visit makes the warning public; anything else, hearsay
included ("nghe don cho nay hay bi ngo doc"), waits for a moderator so one fake
comment cannot sink a place. Default proposed by Claude, pending mentor (PRD Q2).

Negation follows NegEx (Chapman et al. 2001): a trigger up to NEGATION_WINDOW tokens
before a hit, inside the same clause, cancels it ("khong co gian nhu moi nguoi don").
"""

import re
from dataclasses import dataclass
from typing import Literal

from app.services.summary.first_hand import detect_first_hand
from app.services.summary.lexicon import load
from app.services.summary.vi_text import normalize_text

NEGATION_WINDOW = 5  # NegEx default scope; [HIỆU CHỈNH] on Vietnamese data
# Clause ends stop a negation scope (NegEx termination terms): "khong co nuoc nong, co gian".
# Punctuation counts only before a space, so "l.ừ.a đ.ả.o" stays one clause.
_CLAUSE_END = re.compile(r"[,.;:!?]+(?=\s|$)|[\n|]|\bnh[uư]ng\b", re.IGNORECASE)
# shortcut: triggers negate existence or occurrence only; bare "khong" is too common
# ("an khong ngon bi tao thao") and would hide real complaints. Vietnamese trigger list has
# no published source [CẦN NC]; extend from labelled data.
_NEGATION = re.compile(
    r"\b(?:khong (?:he |thay |gap )?(?:co|bi|thay|gap)|khong he|chang (?:co|bi|thay)"
    r"|lam gi co|chua (?:tung|he|bao gio) (?:bi|thay|gap|co))\b"
)
_PSEUDO_NEGATION = re.compile(r"\bkhong (?:nhung|chi|biet)\b")  # "không những bẩn mà còn..."


@dataclass(frozen=True)
class SafetyHit:
    categories: tuple[str, ...]
    visibility: Literal["public", "pending_review"]


def match_safety(body: str) -> SafetyHit | None:
    """Takes the original body: clause breaks are gone once text is normalized."""
    lexicon = load("safety")
    norm_body = normalize_text(body)
    if not lexicon.matches(norm_body):  # negation only removes hits: most comments stop here
        return None
    categories: list[str] = []
    for clause in _CLAUSE_END.split(body):
        norm = normalize_text(clause)
        for group, regex in lexicon.groups.items():
            if group not in categories and any(
                not _negated(norm[: m.start()], m.group()) for m in regex.finditer(norm)
            ):
                categories.append(group)
    if not categories:
        return None
    first_hand = detect_first_hand(norm_body).is_first_hand
    return SafetyHit(
        categories=tuple(g for g in lexicon.groups if g in categories),
        visibility="public" if first_hand else "pending_review",
    )


def _negated(before: str, hit: str) -> bool:
    # the hit's first word joins the window: in "khong co gian" the pattern itself is "co gian"
    window = " ".join([*before.split()[-NEGATION_WINDOW:], hit.split()[0]])
    return bool(_NEGATION.search(window)) and not _PSEUDO_NEGATION.search(window)
