import json
from datetime import UTC, datetime
from typing import Any, cast

import pytest

from app.clients.core_api import CoreApiClient, CorePost, CoreSummary
from app.clients.llm.fake import FakeLlmClient
from app.services.summary.pipeline import SummaryRun
from app.services.summary.schemas import SaveSummaryRequest
from app.workers import summary_worker
from app.workers.summary_worker import (
    DEBOUNCE_MS,
    MAX_WAIT_MS,
    MIN_GAP_MS,
    SummaryScheduler,
    SummaryWorker,
    compute_next_due_ms,
)

POST = "018d9f20-0000-7000-8000-000000000001"


class FakeRedis:
    """The few Redis commands the scheduler and handler use; TTLs are ignored."""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.zset: dict[str, float] = {}
        self.acked: list[str] = []
        self.dead: list[dict[str, str]] = []

    def set(self, key: str, value: object, nx: bool = False, px: int | None = None) -> bool:
        if nx and key in self.kv:
            return False
        self.kv[key] = str(value)
        return True

    def get(self, key: str) -> str | None:
        return self.kv.get(key)

    def delete(self, key: str) -> int:
        return int(self.kv.pop(key, None) is not None)

    def zadd(self, key: str, mapping: dict[str, float]) -> int:
        self.zset.update(mapping)
        return len(mapping)

    def zrangebyscore(self, key: str, low: str, high: float, start: int, num: int) -> list[str]:
        ready = sorted((s, m) for m, s in self.zset.items() if s <= high)
        return [m for _, m in ready][start : start + num]

    def zrem(self, key: str, member: str) -> int:
        return int(self.zset.pop(member, None) is not None)

    def xack(self, stream: str, group: str, message_id: str) -> int:
        self.acked.append(message_id)
        return 1

    def xadd(self, stream: str, fields: dict[str, str]) -> str:
        self.dead.append(fields)
        return "1-0"


def _event(event_type: str = "content.comment.created", **payload: object) -> dict[str, str]:
    envelope = {
        "eventId": "e1",
        "type": event_type,
        "version": 1,
        "occurredAt": "2026-11-05T08:00:00.000Z",
        "producer": "core-api",
        "payload": {"commentId": "c1", "postId": POST} | payload,
    }
    return {"event": json.dumps(envelope)}


@pytest.mark.parametrize(
    ("now", "first", "last_run", "due"),
    [
        (0, 0, None, DEBOUNCE_MS),  # debounce
        (290_000, 0, None, MAX_WAIT_MS),  # max wait wins over a fresh debounce (A2)
        (0, 0, -60_000, MIN_GAP_MS - 60_000),  # ran a minute ago: wait for the gap (A3)
    ],
)
def test_next_due_follows_the_three_timing_rules(
    now: int, first: int, last_run: int | None, due: int
) -> None:
    assert compute_next_due_ms(now, first, last_run) == due


def test_events_push_the_run_back_and_only_one_claim_wins() -> None:
    redis = FakeRedis()
    scheduler = SummaryScheduler(cast(Any, redis))

    scheduler.schedule(POST, 0)
    assert scheduler.schedule(POST, 30_000) == 90_000  # second comment pushes it back
    assert scheduler.claim_due(80_000) == []
    assert scheduler.claim_due(90_000) == [POST]
    assert scheduler.claim_due(90_000) == []  # already claimed

    # A comment during the run starts a new batch, after the 10 min gap (A1).
    assert scheduler.schedule(POST, 95_000) == 90_000 + MIN_GAP_MS


class FakeCoreApi:
    def __init__(self, previous: CoreSummary | None = None, comments_fail: bool = False) -> None:
        self.previous = previous
        self.comments_fail = comments_fail
        self.saved: list[SaveSummaryRequest] = []

    def fetch_post(self, post_id: str) -> CorePost:
        return CorePost(id=post_id, author_id="u-0")

    def fetch_summary(self, post_id: str) -> CoreSummary | None:
        return self.previous

    def fetch_comments(self, post_id: str) -> list[Any]:
        if self.comments_fail:
            raise RuntimeError("core down")
        return []

    def save_summary(self, post_id: str, request: SaveSummaryRequest) -> None:
        self.saved.append(request)


def _worker(redis: FakeRedis, core: FakeCoreApi) -> SummaryWorker:
    return SummaryWorker(
        cast(Any, redis),
        cast(CoreApiClient, core),
        FakeLlmClient(),
        consumer_name="test",
        clock_ms=lambda: 1_000,
    )


def test_comment_event_schedules_the_post_and_is_acked() -> None:
    redis = FakeRedis()

    _worker(redis, FakeCoreApi()).handle_entry("1-0", _event("content.comment.deleted"), 1)

    assert POST in redis.zset and redis.acked == ["1-0"]


def test_unreadable_or_redelivered_events_go_to_dead_letter() -> None:
    redis = FakeRedis()
    worker = _worker(redis, FakeCoreApi())

    worker.handle_entry("1-0", {"event": "not json"}, 1)
    worker.handle_entry("2-0", _event(), summary_worker.MAX_DELIVERIES + 1)

    assert [d["messageId"] for d in redis.dead] == ["1-0", "2-0"]
    assert redis.acked == ["1-0", "2-0"] and not redis.zset


def test_other_event_types_are_acked_and_ignored() -> None:
    redis = FakeRedis()

    _worker(redis, FakeCoreApi()).handle_entry("1-0", _event("content.media.ready"), 1)

    assert redis.acked == ["1-0"] and not redis.zset


def test_run_saves_the_result_to_core() -> None:
    core = FakeCoreApi()

    _worker(FakeRedis(), core).summarize_post(POST)

    assert [r.status for r in core.saved] == ["no_comments"]


def test_failed_run_keeps_the_previous_ready_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    core = FakeCoreApi(previous=CoreSummary(status="ready", input_hash="h"))
    monkeypatch.setattr(
        summary_worker,
        "run_summary",
        lambda **_: SummaryRun(
            SaveSummaryRequest(status="failed", generated_at=datetime(2026, 11, 5, tzinfo=UTC))
        ),  # pyright: ignore[reportUnknownLambdaType]
    )

    _worker(FakeRedis(), core).summarize_post(POST)

    assert core.saved == []


def test_core_error_reschedules_the_post() -> None:
    redis = FakeRedis()

    _worker(redis, FakeCoreApi(comments_fail=True)).summarize_post(POST)

    assert POST in redis.zset
