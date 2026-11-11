"""Comment labels and safety results kept between runs.

Labelling a comment once, when it is written, makes a summary run cost the same for 1,000 or
1,000,000 comments (DeepResearch_AI_Summary_1_trieu_binh_luan.md §4.1). The store is a port;
RedisLabelStore is its adapter. Core does not keep AI labels (Thành, 2026-11-11: they are
tied to our model version and would bloat its comments table), so Redis with a TTL stays.

A label is used only while it is still true: same model version and same text (sha256 of the
body). Safety results are kept so a warning outside core's sample is not lost. Both are
derived data with a TTL, never the comment text, so losing Redis only means labelling again.
Whole-post counts come from core (PR be #128), not from here.
"""

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

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
class StoredSafety:
    """A safety hit decided at write time: the categories, and public or held for review."""

    comment_id: str
    categories: tuple[str, ...]
    visibility: Literal["public", "pending_review"]


class LabelStore(Protocol):
    def get_many(self, post_id: str, comment_ids: Iterable[str]) -> dict[str, StoredLabel]: ...

    def put(self, post_id: str, comment_id: str, author_id: str, label: StoredLabel) -> None: ...

    def remove(self, post_id: str, comment_id: str) -> None: ...

    def put_safety(self, post_id: str, hit: StoredSafety) -> None: ...

    def get_safety(self, post_id: str) -> list[StoredSafety]: ...


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
    def __init__(self, client: Any) -> None:
        self.redis = client

    def get_many(self, post_id: str, comment_ids: Iterable[str]) -> dict[str, StoredLabel]:
        ids = list(comment_ids)
        if not ids:
            return {}
        rows = cast(list[str | None], self.redis.hmget(_labels_key(post_id), ids))
        return {cid: _decode(raw) for cid, raw in zip(ids, rows, strict=True) if raw}

    def put(self, post_id: str, comment_id: str, author_id: str, label: StoredLabel) -> None:
        self.redis.hset(_labels_key(post_id), comment_id, _encode(label))
        self.redis.expire(_labels_key(post_id), TTL_SECONDS)

    def remove(self, post_id: str, comment_id: str) -> None:
        self.redis.hdel(_labels_key(post_id), comment_id)
        self.redis.hdel(_safety_key(post_id), comment_id)

    def put_safety(self, post_id: str, hit: StoredSafety) -> None:
        value = json.dumps({"c": list(hit.categories), "v": hit.visibility})
        self.redis.hset(_safety_key(post_id), hit.comment_id, value)
        self.redis.expire(_safety_key(post_id), TTL_SECONDS)

    def get_safety(self, post_id: str) -> list[StoredSafety]:
        rows = cast(dict[str, str], self.redis.hgetall(_safety_key(post_id)))
        hits: list[StoredSafety] = []
        for cid, raw in rows.items():
            data = json.loads(raw)
            hits.append(StoredSafety(cid, tuple(data["c"]), data["v"]))
        return hits


def _labels_key(post_id: str) -> str:
    return f"ai:labels:{post_id}"


def _safety_key(post_id: str) -> str:
    return f"ai:safety:{post_id}"


def _encode(label: StoredLabel) -> str:
    flags = "".join("1" if getattr(label.labels, f) else "0" for f in FLAGS)
    return json.dumps({"v": label.version, "h": label.content_hash, "f": flags})


def _decode(raw: str) -> StoredLabel:
    data = json.loads(raw)
    labels = CommentLabels(**{f: bit == "1" for f, bit in zip(FLAGS, data["f"], strict=True)})
    return StoredLabel(labels=labels, version=data["v"], content_hash=data["h"])
