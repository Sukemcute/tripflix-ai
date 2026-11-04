"""Rule filters L1-L6, L8, L9, L11, L12 (QT Bước 5). L7 and L10 wait for GĐ2.

Each dropped comment gets exactly one rule code, the first rule that fires.
L11 needs no code: a reply is judged as a standalone comment, so it passes only on its own L5.
"""

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.services.summary.lexicon import load
from app.services.summary.schemas import CommentIn
from app.services.summary.vi_text import count_syllables, to_norm, to_raw

MAX_AGE = timedelta(days=365)  # Tripadvisor: review within one year of the visit
MIN_SYLLABLES = 4  # QT L5, [HIỆU CHỈNH]
# shortcut: common TLDs only, not the full public suffix list; extend when seed data shows misses.
_LINK = re.compile(
    r"(?:https?://|www\.)\S|\b[a-z0-9-]+\.(?:com|vn|net|org|info|io|me|ly|co|link|shop|xyz|top|site)\b",
    re.IGNORECASE,
)
_LINK_SPELLED = re.compile(r"\b(?:cham|dot) (?:com|vn|net)\b")  # "vinpearl cham com"
_KEEPS_MIXED = ("safety", "complaint", "service_terms")


@dataclass(frozen=True)
class Candidate:
    """One author's usable comments merged into one voice (L9)."""

    author_id: str
    comment_ids: tuple[str, ...]
    text: str  # to_raw bodies joined by " | "
    text_norm: str
    like_count: int  # highest among the merged comments
    created_at: datetime  # latest among the merged comments
    suspect: bool  # holds the kept copy of a cross-account duplicate (L8): not counted as a person


@dataclass(frozen=True)
class FilterResult:
    candidates: list[Candidate]
    dropped: dict[str, str]  # comment_id -> rule code


def filter_comments(comments: Sequence[CommentIn], now: datetime) -> FilterResult:
    dropped: dict[str, str] = {}
    kept: list[tuple[CommentIn, str, str]] = []
    for comment in comments:
        text, norm = to_raw(comment.body), to_norm(comment.body)
        reason = _rule_for(comment, text, norm, now)
        if reason:
            dropped[comment.comment_id] = reason
        else:
            kept.append((comment, text, norm))
    # Same input in any order -> same output, so input_hash stays stable.
    kept.sort(key=lambda item: (item[0].created_at, item[0].comment_id))

    # L8: same text from 2+ accounts -> keep the earliest copy, flag it.
    authors: defaultdict[str, set[str]] = defaultdict(set)
    for comment, _, norm in kept:
        authors[norm].add(comment.author_id)
    copied = {norm for norm, ids in authors.items() if len(ids) >= 2}
    seen: set[str] = set()

    # L9: merge each author's comments; drop the author's own repeats.
    groups: dict[str, list[tuple[CommentIn, str, str]]] = {}
    for comment, text, norm in kept:
        group = groups.setdefault(comment.author_id, [])
        if (norm in copied and norm in seen) or any(norm == n for _, _, n in group):
            dropped[comment.comment_id] = "L8" if norm in copied else "L9"
            continue
        seen.add(norm)
        group.append((comment, text, norm))

    candidates = [
        Candidate(
            author_id=author_id,
            comment_ids=tuple(c.comment_id for c, _, _ in group),
            text=" | ".join(text for _, text, _ in group),
            text_norm=" | ".join(norm for _, _, norm in group),
            like_count=max(c.like_count for c, _, _ in group),
            created_at=group[-1][0].created_at,
            suspect=any(norm in copied for _, _, norm in group),
        )
        for author_id, group in groups.items()
        if group
    ]
    return FilterResult(candidates=candidates, dropped=dropped)


def _rule_for(comment: CommentIn, text: str, norm: str, now: datetime) -> str | None:
    if comment.status != "visible":
        return "L1"
    if now - comment.created_at > MAX_AGE:
        return "L2"
    if comment.is_post_author:
        return "L3"
    if not norm:
        return "L4"
    if _LINK.search(text) or _LINK_SPELLED.search(norm):
        return "L6"
    is_safety = bool(load("safety").matches(norm))
    if count_syllables(norm) < MIN_SYLLABLES and not is_safety:
        return "L5"
    if load("video_reaction").matches(norm) and not any(
        load(name).matches(norm) for name in _KEEPS_MIXED
    ):
        return "L12"
    return None
