"""Which comments the classifier labels when a post has more than the cap.

"Newest N" leaned on the last hours and left out older, much-liked comments, which then fell
to rules that miss 93% of first-hand writers (BENCH_AI_SUMMARY_2026-11-11). Instead:
- safety hits first: their first-hand label decides public warning or moderator queue;
- the rest split into strata (root or reply, week of writing), each stratum gets slots in
  proportion to its size (largest remainder), so every period and both kinds are covered;
- inside a stratum, weighted reservoir sampling (Efraimidis & Spirakis 2006, A-Res): key
  u^(1/w) with w = 1 + likes, the k largest keys win, so liked comments are more likely in.
The random u comes from crc32 of the comment id: the same comments always give the same
sample, so the input hash only moves when the comments do.
"""

import math
import zlib
from collections import defaultdict
from collections.abc import Collection, Sequence

from app.services.summary.schemas import CommentIn

WEEK_SECONDS = 7 * 24 * 3600


def pick_for_labels(
    comments: Sequence[CommentIn], size: int, *, first: Collection[str] = ()
) -> list[CommentIn]:
    """At most `size` comments: those in `first`, then a stratified weighted sample."""
    if len(comments) <= size:
        return list(comments)
    must = [c for c in comments if c.comment_id in first][:size]
    rest = [c for c in comments if c.comment_id not in first]
    slots = size - len(must)
    if slots <= 0:
        return must
    strata: dict[tuple[bool, int], list[CommentIn]] = defaultdict(list)
    for c in rest:
        strata[(c.parent_id is not None, int(c.created_at.timestamp()) // WEEK_SECONDS)].append(c)
    picked: list[CommentIn] = []
    for stratum, quota in _allocate(strata, slots).items():
        ranked = sorted(strata[stratum], key=_reservoir_key, reverse=True)
        picked += ranked[:quota]
    return must + picked


def _allocate(strata: dict[tuple[bool, int], list[CommentIn]], slots: int) -> dict:
    total = sum(len(v) for v in strata.values())
    exact = {k: slots * len(v) / total for k, v in strata.items()}
    quota = {k: math.floor(x) for k, x in exact.items()}
    # largest remainder: the slots left go to the strata the floor cut most; ties by key
    for k in sorted(exact, key=lambda k: (quota[k] - exact[k], k))[: slots - sum(quota.values())]:
        quota[k] += 1
    return quota


def _reservoir_key(c: CommentIn) -> float:
    u = (zlib.crc32(c.comment_id.encode()) + 1) / (2**32 + 1)  # in (0, 1), fixed per comment
    return u ** (1 / (1 + max(c.like_count, 0)))
