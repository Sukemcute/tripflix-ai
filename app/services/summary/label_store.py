"""Comment labels kept between runs, and per-post counts over every labelled comment.

Labelling a comment once, when it is written, makes a summary run cost the same for 1,000 or
1,000,000 comments (DeepResearch_AI_Summary_1_trieu_binh_luan.md §4.1). The store is a port:
RedisLabelStore is the first adapter (Bảo, 2026-11-11: Redis first, core later); a core-backed
adapter with the same methods replaces it once Thành agrees where labels live.

A label is used only while it is still true: same model version and same text (sha256 of the
body). Labels are derived data with a TTL, never the comment text, so losing Redis only means
labelling again.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.services.summary.comment_classifier import CommentLabels

TTL_SECONDS = 30 * 24 * 3600  # [HIỆU CHỈNH] refreshed on every write
FLAGS = tuple(CommentLabels.__dataclass_fields__)


def content_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class StoredLabel:
    labels: CommentLabels
    version: str
    content_hash: str


@dataclass(frozen=True)
class PostStats:
    """Counts over every labelled comment of the post, not only the ones sent to the LLM."""

    labelled_comments: int
    first_hand_comments: int
    complaint_comments: int
    praise_comments: int
    writers: int  # HyperLogLog estimates: ~0.81% standard error (Redis docs)
    first_hand_writers: int


class LabelStore(Protocol):
    def get_many(self, post_id: str, comment_ids: Iterable[str]) -> dict[str, StoredLabel]: ...

    def put(self, post_id: str, comment_id: str, author_id: str, label: StoredLabel) -> None: ...

    def remove(self, post_id: str, comment_id: str) -> None: ...

    def stats(self, post_id: str) -> PostStats: ...


def fresh_labels(
    stored: Mapping[str, StoredLabel], bodies: Mapping[str, str], version: str
) -> dict[str, CommentLabels]:
    """Stored labels that still describe the comment: same model, same text."""
    return {
        cid: s.labels
        for cid, s in stored.items()
        if cid in bodies and s.version == version and s.content_hash == content_hash(bodies[cid])
    }


class RedisLabelStore:
    """shortcut: put/remove read then write in two steps, so two label workers changing the
    same comment at once can skew a counter by one; run one label worker, or move the update
    into a Lua script before scaling it out. HyperLogLog cannot forget a writer, so writers
    stays an upper bound after deletions."""

    def __init__(self, client: Any) -> None:
        self.redis = client

    def get_many(self, post_id: str, comment_ids: Iterable[str]) -> dict[str, StoredLabel]:
        ids = list(comment_ids)
        if not ids:
            return {}
        rows = cast(list[str | None], self.redis.hmget(_labels_key(post_id), ids))
        return {cid: _decode(raw) for cid, raw in zip(ids, rows, strict=True) if raw}

    def put(self, post_id: str, comment_id: str, author_id: str, label: StoredLabel) -> None:
        key = _labels_key(post_id)
        old_raw = cast(str | None, self.redis.hget(key, comment_id))
        old = _decode(old_raw) if old_raw else None
        if old == label:
            return  # a redelivered event: counted already
        self.redis.hset(key, comment_id, _encode(label))
        self._count(post_id, old.labels if old else None, label.labels)
        self.redis.pfadd(_writers_key(post_id), author_id)
        if label.labels.is_first_hand:
            self.redis.pfadd(_writers_key(post_id, "first_hand"), author_id)
        keys = (key, _stats_key(post_id), _writers_key(post_id))
        for k in (*keys, _writers_key(post_id, "first_hand")):
            self.redis.expire(k, TTL_SECONDS)

    def remove(self, post_id: str, comment_id: str) -> None:
        old_raw = cast(str | None, self.redis.hget(_labels_key(post_id), comment_id))
        if old_raw:
            self.redis.hdel(_labels_key(post_id), comment_id)
            self._count(post_id, _decode(old_raw).labels, None)

    def stats(self, post_id: str) -> PostStats:
        raw = cast(dict[str, str], self.redis.hgetall(_stats_key(post_id)))
        n = {k: max(0, int(v)) for k, v in raw.items()}
        return PostStats(
            labelled_comments=n.get("labelled", 0),
            first_hand_comments=n.get("is_first_hand", 0),
            complaint_comments=n.get("is_complaint", 0),
            praise_comments=n.get("is_praise", 0),
            writers=int(cast(int, self.redis.pfcount(_writers_key(post_id)))),
            first_hand_writers=int(
                cast(int, self.redis.pfcount(_writers_key(post_id, "first_hand")))
            ),
        )

    def _count(self, post_id: str, old: CommentLabels | None, new: CommentLabels | None) -> None:
        key = _stats_key(post_id)
        if (old is None) != (new is None):
            self.redis.hincrby(key, "labelled", 1 if new else -1)
        for flag in FLAGS:
            delta = int(bool(new and getattr(new, flag))) - int(bool(old and getattr(old, flag)))
            if delta:
                self.redis.hincrby(key, flag, delta)


def _labels_key(post_id: str) -> str:
    return f"ai:labels:{post_id}"


def _stats_key(post_id: str) -> str:
    return f"ai:labelstats:{post_id}"


def _writers_key(post_id: str, kind: str = "all") -> str:
    return f"ai:writers:{kind}:{post_id}"


def _encode(label: StoredLabel) -> str:
    flags = "".join("1" if getattr(label.labels, f) else "0" for f in FLAGS)
    return json.dumps({"v": label.version, "h": label.content_hash, "f": flags})


def _decode(raw: str) -> StoredLabel:
    data = json.loads(raw)
    labels = CommentLabels(**{f: bit == "1" for f, bit in zip(FLAGS, data["f"], strict=True)})
    return StoredLabel(labels=labels, version=data["v"], content_hash=data["h"])
