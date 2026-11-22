import json
import os
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from app.services.summary.comment_classifier import CommentLabels
from app.services.summary.label_store import (
    RedisLabelStore,
    StoredLabel,
    StoredSafety,
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
    """Hashes and the stream calls the label worker makes."""

    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
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

    def hgetall(self, key: str) -> dict[str, str]:
        return dict(self.hashes.get(key, {}))

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

    def __init__(
        self,
        label: CommentLabels = FIRST_HAND,
        error: Exception | None = None,
        by_text: dict[str, CommentLabels] | None = None,
    ) -> None:
        self.label = label
        self.error = error
        self.by_text = by_text or {}
        self.seen: list[str] = []

    def classify(self, pairs: Sequence[tuple[str, str]]) -> list[CommentLabels]:
        if self.error:
            raise self.error
        self.seen += [text for text, _ in pairs]
        return [self.by_text.get(text, self.label) for text, _ in pairs]


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


def test_store_keeps_labels_and_safety_until_the_comment_goes() -> None:
    store = RedisLabelStore(FakeRedis())
    store.put(POST, "c1", "u1", StoredLabel(FIRST_HAND, "v1", content_hash("a")))
    store.put_safety(POST, StoredSafety("c1", ("ngo_doc",), "public"))

    assert set(store.get_many(POST, ["c1", "c2"])) == {"c1"}
    assert store.get_safety(POST) == [StoredSafety("c1", ("ngo_doc",), "public")]

    store.remove(POST, "c1")
    assert store.get_many(POST, ["c1"]) == {} and store.get_safety(POST) == []


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


def test_hidden_or_deleted_comments_lose_their_label_and_safety_result() -> None:
    redis = FakeRedis()
    store = RedisLabelStore(redis)
    store.put(POST, "c1", "u1", StoredLabel(FIRST_HAND, "v1", content_hash("x")))
    store.put_safety(POST, StoredSafety("c1", ("ngo_doc",), "public"))

    LabelWorker(redis, store, StubClassifier()).handle_batch([_event("hidden", "c1")])

    assert store.get_many(POST, ["c1"]) == {} and store.get_safety(POST) == []


def test_safety_hits_are_kept_for_roots_and_replies_without_the_text() -> None:
    """A warning outside core's sample must still reach the summary (PR be #128)."""
    redis = FakeRedis()
    store = RedisLabelStore(redis)
    own_reply = "Mình cũng bị ngộ độc sau bữa tối ở đây"
    classifier = StubClassifier(FIRST_HAND, by_text={"nghe nói ở đây hay bị ngộ độc": NONE})
    worker = LabelWorker(redis, store, classifier, clock=lambda: NOW)

    worker.handle_batch(
        [
            _event("created", "c1", "Mình ăn hải sản ở đây xong bị ngộ độc cả nhà"),
            _event("created", "c2", "nghe nói ở đây hay bị ngộ độc", parentCommentId="c1"),
            _event("created", "c3", "phòng sạch, view biển đẹp, nhân viên dễ thương"),
            _event("created", "c4", own_reply, parentCommentId="c1"),
        ]
    )

    kept = {k.comment_id: k for k in store.get_safety(POST)}
    assert set(kept) == {"c1", "c2", "c4"}
    assert kept["c1"].visibility == "public"  # the model says first-hand
    # replies are read by the model too, as a summary run would: the same visibility either way
    assert kept["c2"].visibility == "pending_review"
    assert kept["c4"].visibility == "public"
    assert set(store.get_many(POST, ["c2", "c4"])) == set()  # reply labels are not stored
    assert all("hải sản" not in raw for raw in redis.hashes["ai:safety:" + POST].values())


def test_an_edit_that_removes_the_safety_words_removes_the_kept_result() -> None:
    redis = FakeRedis()
    store = RedisLabelStore(redis)
    worker = LabelWorker(redis, store, StubClassifier(), clock=lambda: NOW)

    worker.handle_batch([_event("created", "c1", "Mình ăn ở đây xong bị ngộ độc")])
    worker.handle_batch([_event("updated", "c1", "Mình ăn ở đây, đồ ăn hơi mặn")])

    assert store.get_safety(POST) == []


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


@pytest.mark.parametrize("name", ["server-1", ""])
def test_both_workers_take_their_consumer_name_from_settings(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """A fixed name stops every container rebuild from adding a dead consumer (Phong)."""
    from app.core.config import get_settings
    from app.workers import label_worker, summary_worker

    for key, value in {
        "LLM_PROVIDER": "fake",
        "CLASSIFIER_ENABLED": "false",
        "SUMMARY_WORKER_CONSUMER_NAME": name,
        "LABEL_WORKER_CONSUMER_NAME": name,
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    names: list[str] = []
    monkeypatch.setattr(
        summary_worker.SummaryWorker, "run_forever", lambda s: names.append(s.consumer)
    )
    monkeypatch.setattr(label_worker.LabelWorker, "run_forever", lambda s: names.append(s.consumer))
    try:
        summary_worker.main()
        label_worker.main()
    finally:
        get_settings.cache_clear()

    if name:
        assert names == ["server-1", "server-1"]
    else:  # hostname-PID as before
        assert names[0].endswith(f"-{os.getpid()}") and names[1].endswith(f"-{os.getpid()}-labels")
