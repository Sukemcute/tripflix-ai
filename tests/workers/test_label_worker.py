import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from app.services.summary.comment_classifier import CommentLabels
from app.services.summary.label_store import (
    RedisLabelStore,
    StoredLabel,
    content_hash,
    fresh_labels,
)
from app.workers.label_worker import LabelWorker

POST = "018d9f20-0000-7000-8000-000000000001"
NOW = datetime(2026, 11, 11, tzinfo=UTC)
NONE = CommentLabels(False, False, False, False, False, False)
FIRST_HAND = replace(NONE, is_experienced=True, is_first_hand=True)
COMPLAINT = replace(FIRST_HAND, is_complaint=True)


class FakeRedis:
    """Hashes, HyperLogLog (as exact sets) and the stream calls the label worker makes."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.hll: dict[str, set[str]] = {}
        self.acked: list[str] = []
        self.dead: list[dict[str, str]] = []

    def hget(self, key: str, field: str) -> str | None:
        return self.hashes.get(key, {}).get(field)

    def hmget(self, key: str, fields: list[str]) -> list[str | None]:
        return [self.hashes.get(key, {}).get(f) for f in fields]

    def hset(self, key: str, field: str, value: str) -> int:
        self.hashes.setdefault(key, {})[field] = value
        return 1

    def hdel(self, key: str, field: str) -> int:
        return int(self.hashes.get(key, {}).pop(field, None) is not None)

    def hincrby(self, key: str, field: str, by: int) -> int:
        h = self.hashes.setdefault(key, {})
        h[field] = str(int(h.get(field, "0")) + by)
        return int(h[field])

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

    def pfadd(self, key: str, value: str) -> int:
        self.hll.setdefault(key, set()).add(value)
        return 1

    def pfcount(self, key: str) -> int:
        return len(self.hll.get(key, set()))

    def expire(self, key: str, seconds: int) -> bool:
        return True

    def xack(self, stream: str, group: str, message_id: str) -> int:
        self.acked.append(message_id)
        return 1

    def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self.dead.append(fields)
        return "1-0"


class StubClassifier:
    version = "v1"

    def __init__(self, label: CommentLabels = FIRST_HAND, error: Exception | None = None) -> None:
        self.label = label
        self.error = error
        self.seen: list[str] = []

    def classify(self, pairs: Sequence[tuple[str, str]]) -> list[CommentLabels]:
        if self.error:
            raise self.error
        self.seen += [text for text, _ in pairs]
        return [self.label for _ in pairs]


def _event(kind: str, cid: str, body: str = "", **extra: Any) -> tuple[str, dict[str, str]]:
    payload = {"commentId": cid, "postId": POST, "authorId": f"a-{cid}", "body": body} | extra
    envelope = {
        "eventId": f"e-{cid}",
        "type": f"content.comment.{kind}",
        "version": 1,
        "occurredAt": "2026-11-11T08:00:00.000Z",
        "producer": "core-api",
        "payload": payload,
    }
    return f"{cid}-0", {"event": json.dumps(envelope)}


def test_store_counts_once_per_comment_and_follows_edits_and_deletes() -> None:
    store = RedisLabelStore(FakeRedis())
    label = StoredLabel(FIRST_HAND, "v1", content_hash("a"))

    store.put(POST, "c1", "u1", label)
    store.put(POST, "c1", "u1", label)  # redelivered: counted once
    store.put(POST, "c2", "u2", StoredLabel(COMPLAINT, "v1", content_hash("b")))
    store.put(POST, "c2", "u2", StoredLabel(NONE, "v1", content_hash("b, sửa")))  # edited
    stats = store.stats(POST)
    assert (stats.labelled_comments, stats.first_hand_comments, stats.complaint_comments) == (
        2,
        1,
        0,
    )
    assert stats.writers == 2

    store.remove(POST, "c1")
    assert store.stats(POST).first_hand_comments == 0
    assert store.stats(POST).labelled_comments == 1
    assert set(store.get_many(POST, ["c1", "c2"])) == {"c2"}


def test_only_labels_of_the_same_text_and_model_are_reused() -> None:
    stored = {
        "same": StoredLabel(FIRST_HAND, "v1", content_hash("phòng đẹp")),
        "edited": StoredLabel(FIRST_HAND, "v1", content_hash("phòng đẹp")),
        "old_model": StoredLabel(FIRST_HAND, "v0", content_hash("phòng đẹp")),
    }
    bodies = {"same": "phòng đẹp", "edited": "phòng bẩn", "old_model": "phòng đẹp"}

    assert set(fresh_labels(stored, bodies, "v1")) == {"same"}


def test_worker_labels_root_comments_and_skips_what_rules_already_drop() -> None:
    redis = FakeRedis()
    classifier = StubClassifier()
    worker = LabelWorker(redis, RedisLabelStore(redis), classifier, clock=lambda: NOW)

    worker.handle_batch(
        [
            _event("created", "c1", "Mình ở đây 2 đêm, phòng sạch, nhân viên dễ thương"),
            _event("created", "c2", "săn sale tại shopee.vn/abc nha mọi người"),  # link: L6
            _event("created", "c3", "Đúng rồi bạn", parentCommentId="c1"),  # reply: later
            _event("created", "c4", "bị ngộ độc"),  # too short, but a safety hit
        ]
    )

    assert classifier.seen == [
        "Mình ở đây 2 đêm, phòng sạch, nhân viên dễ thương",
        "bị ngộ độc",
    ]
    assert set(RedisLabelStore(redis).get_many(POST, ["c1", "c2", "c3", "c4"])) == {"c1", "c4"}
    assert redis.acked == ["c1-0", "c2-0", "c3-0", "c4-0"]


def test_hidden_or_deleted_comments_leave_the_counts() -> None:
    redis = FakeRedis()
    store = RedisLabelStore(redis)
    store.put(POST, "c1", "u1", StoredLabel(FIRST_HAND, "v1", content_hash("x")))

    LabelWorker(redis, store, StubClassifier()).handle_batch([_event("hidden", "c1")])

    assert store.stats(POST).labelled_comments == 0


def test_a_failing_classifier_acks_and_leaves_labelling_to_summary_runs() -> None:
    redis = FakeRedis()
    worker = LabelWorker(
        redis, RedisLabelStore(redis), StubClassifier(error=RuntimeError("onnx")), clock=lambda: NOW
    )

    worker.handle_batch([_event("created", "c1", "Mình ở đây 2 đêm, phòng sạch, đáng tiền")])

    assert redis.acked == ["c1-0"] and redis.hashes == {}


def test_an_unreadable_event_goes_to_dead_letter_and_is_acked() -> None:
    redis = FakeRedis()

    LabelWorker(redis, RedisLabelStore(redis), StubClassifier()).handle_batch(
        [("9-0", {"event": "not json"})]
    )

    assert redis.dead[0]["group"] == "ai-labels" and redis.acked == ["9-0"]
