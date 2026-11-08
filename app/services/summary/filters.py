"""Rule filters L1-L6, L8, L9, L11-L13 (QT Bước 5). L7 and L10 wait for GĐ2.

Each dropped comment gets exactly one rule code, the first rule that fires.
L11 needs no code: a reply is judged as a standalone comment, so it passes only on its own L5.
L13 drops prompt-injection attempts: layer 1 of 3 (OWASP LLM01), spotlighting (P8) and the
validator (P10) stay.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.services.summary import complaint_model
from app.services.summary.injection import match_injection
from app.services.summary.lexicon import load
from app.services.summary.safety import match_safety
from app.services.summary.schemas import CommentIn
from app.services.summary.vi_text import MENTION, clean_text, count_syllables, normalize_text

MAX_AGE = timedelta(days=365)  # Tripadvisor: review within one year of the visit
MIN_SYLLABLES = 4  # QT L5, [HIỆU CHỈNH]
# Jindal & Liu (2007): Broder shingles, similarity > 0.9 marks a near-duplicate review;
# WSDM 2008 used word 2-gram Jaccard. Tuned on long Amazon reviews: [HIỆU CHỈNH] for comments.
NEAR_DUP_JACCARD = 0.9
PARENT_CONTEXT_CHARS = 128  # Henderson et al. (2019) cut each ancestor to 128 characters
_NO_PARENT_CONTEXT = {"L1", "L13"}  # hidden/deleted or an injection never travels as context
_NOT_A_VOTE = {"L1", "L2", "L3", "L13"}  # hidden, stale, the creator, or an attack
_PLUS_ONE = re.compile(r"^\s*\+\s*1\b")
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
    text: str  # clean_text bodies joined by " | "
    text_norm: str
    like_count: int  # highest among the merged comments
    created_at: datetime  # latest among the merged comments
    is_suspect: (
        bool  # holds the kept copy of a cross-account duplicate (L8): not counted as a person
    )
    # Parent texts of this author's replies, cut to PARENT_CONTEXT_CHARS: context for the
    # LLM, never this author's opinion (CQA: the question frames the answer).
    contexts: tuple[str, ...] = ()
    # Authors whose reply agrees with one of these comments ("dung roi", "+1"): code counts
    # them for V3 "2+ authors" (agree/disagree labels as in ABCD); no text goes to the LLM.
    supporters: frozenset[str] = frozenset()


@dataclass(frozen=True)
class FilterResult:
    candidates: list[Candidate]
    dropped: dict[str, str]  # comment_id -> rule code


def filter_comments(comments: Sequence[CommentIn], now: datetime) -> FilterResult:
    dropped: dict[str, str] = {}
    kept: list[tuple[CommentIn, str, str]] = []
    for comment in comments:
        text, norm = clean_text(comment.body), normalize_text(comment.body)
        reason = _rule_for(comment, text, norm, now)
        if reason:
            dropped[comment.comment_id] = reason
        else:
            kept.append((comment, text, norm))
    # Same input in any order -> same output, so input_hash stays stable.
    kept.sort(key=lambda item: (item[0].created_at, item[0].comment_id))

    # L8: same or near-same text from 2+ accounts -> keep the earliest copy, flag it.
    clusters = _near_duplicate_clusters([norm for _, _, norm in kept])
    authors: dict[int, set[str]] = {}
    for (comment, _, _), cluster in zip(kept, clusters, strict=True):
        authors.setdefault(cluster, set()).add(comment.author_id)
    copied = {cluster for cluster, ids in authors.items() if len(ids) >= 2}
    seen: set[int] = set()

    # L9: merge each author's comments; drop the author's own (near) repeats.
    groups: dict[str, list[tuple[CommentIn, str, str]]] = {}
    group_clusters: dict[str, set[int]] = {}
    for (comment, text, norm), cluster in zip(kept, clusters, strict=True):
        group = groups.setdefault(comment.author_id, [])
        own = group_clusters.setdefault(comment.author_id, set())
        if (cluster in copied and cluster in seen) or cluster in own:
            dropped[comment.comment_id] = "L8" if cluster in copied else "L9"
            continue
        seen.add(cluster)
        own.add(cluster)
        group.append((comment, text, norm))

    # Threads: a reply leans on its parent for context, and an agreeing reply is a vote.
    by_id = {c.comment_id: c for c in comments}

    def find_parent(c: CommentIn) -> CommentIn | None:
        parent = by_id.get(c.parent_id) if c.parent_id else None
        if parent is None or dropped.get(parent.comment_id) in _NO_PARENT_CONTEXT:
            return None
        return parent if parent.author_id != c.author_id else None

    votes: dict[str, set[str]] = {}
    for c in comments:
        parent = find_parent(c)
        if parent and dropped.get(c.comment_id) not in _NOT_A_VOTE and _agrees(c.body):
            votes.setdefault(parent.comment_id, set()).add(c.author_id)

    def collect_contexts(group: list[tuple[CommentIn, str, str]]) -> tuple[str, ...]:
        parents = (find_parent(c) for c, _, _ in group)
        texts = (clean_text(p.body)[:PARENT_CONTEXT_CHARS] for p in parents if p)
        return tuple(dict.fromkeys(texts))  # dedupe, keep order

    candidates = [
        Candidate(
            author_id=author_id,
            comment_ids=tuple(c.comment_id for c, _, _ in group),
            text=" | ".join(text for _, text, _ in group),
            text_norm=" | ".join(norm for _, _, norm in group),
            like_count=max(c.like_count for c, _, _ in group),
            created_at=group[-1][0].created_at,
            is_suspect=bool(group_clusters[author_id] & copied),
            contexts=collect_contexts(group),
            supporters=frozenset().union(*(votes.get(c.comment_id, ()) for c, _, _ in group))
            - {author_id},
        )
        for author_id, group in groups.items()
        if group
    ]
    return FilterResult(candidates=candidates, dropped=dropped)


def _agrees(body: str) -> bool:
    if _PLUS_ONE.search(body):
        return True
    groups = load("agreement").matches(normalize_text(body))
    return "agree" in groups and "disagree" not in groups


def _near_duplicate_clusters(norms: Sequence[str]) -> list[int]:
    """Cluster id per text: the first earlier text with word 2-gram Jaccard > NEAR_DUP_JACCARD.

    shortcut: compares each text with every earlier cluster head, O(n * clusters); fine for
    the ~1,000 comments of one post, switch to MinHash (Jindal & Liu 2014) when posts get larger.
    """
    heads: list[tuple[frozenset[tuple[str, ...]], int]] = []
    exact: dict[str, int] = {}
    clusters: list[int] = []
    for norm in norms:
        if norm in exact:
            clusters.append(exact[norm])
            continue
        tokens = norm.split()
        grams = frozenset(zip(tokens, tokens[1:], strict=False)) or frozenset({tuple(tokens)})
        cluster = next(
            (
                cid
                for head, cid in heads
                # Jaccard > t needs the smaller set to hold > t of the larger: skip early
                if min(len(head), len(grams)) > NEAR_DUP_JACCARD * max(len(head), len(grams))
                and len(head & grams) > NEAR_DUP_JACCARD * len(head | grams)
            ),
            None,
        )
        if cluster is None:
            cluster = len(heads)
            heads.append((grams, cluster))
        exact[norm] = cluster
        clusters.append(cluster)
    return clusters


def _rule_for(comment: CommentIn, text: str, norm: str, now: datetime) -> str | None:
    if comment.status != "visible":
        return "L1"
    if now - comment.created_at > MAX_AGE:
        return "L2"
    if comment.is_post_author:
        return "L3"
    if match_injection(comment.body):
        return "L13"
    if not norm:
        return "L4"
    if _LINK.search(text) or _LINK_SPELLED.search(norm) or load("redirect").matches(norm):
        return "L6"
    is_safety = match_safety(comment.body) is not None
    if count_syllables(norm) < MIN_SYLLABLES and not is_safety:
        return "L5"
    # Lexicon only, never the classifier's video_reaction label: dropping on it lost real
    # visits it misread ("cô chủ dễ thương, cho mượn xe đạp free"), point recall 0.90 -> 0.72
    # on the live eval (BAO_CAO).
    off_topic = load("video_reaction").matches(norm) or MENTION in text  # Meta: tag bait
    if off_topic and not (
        any(load(name).matches(norm) for name in _KEEPS_MIXED)
        or complaint_model.is_complaint(comment.body)
    ):
        return "L12"
    return None
