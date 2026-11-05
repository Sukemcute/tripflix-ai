"""Summary worker against a real Redis; core and the LLM are faked.

Runs only when REDIS_TEST_URL points to a throwaway Redis (the test flushes it), e.g.
`docker run -d --rm -p 6390:6379 redis:7.4-alpine` then
`REDIS_TEST_URL=redis://localhost:6390/15 uv run pytest tests/workers`.
"""

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
import redis

from app.clients.core_api import CoreApiClient, CoreComment, CorePost, CoreSummary
from app.clients.llm.fake import FakeLlmClient
from app.services.summary.schemas import SaveSummaryRequest
from app.workers import summary_worker as sw

REDIS_URL = os.environ.get("REDIS_TEST_URL")
pytestmark = pytest.mark.skipif(not REDIS_URL, reason="REDIS_TEST_URL not set")

POST = "018d9f20-0000-7000-8000-000000000001"
TEXTS = [
    "Phòng rộng, view biển nhìn thẳng ra bãi tắm rất đẹp",
    "Mình ở 2 đêm, nhân viên lễ tân nhiệt tình hỗ trợ check-in sớm",
    "Bữa sáng nhiều món, hải sản tươi, đáng tiền",
    "Hồ bơi vô cực chụp ảnh sống ảo cực chill lúc hoàng hôn",
    "Đi taxi từ sân bay mất tầm 20 phút, đường dễ tìm",
    "Mình ở đây tuần trước, ăn buffet xong bị ngộ độc cả nhà",
]
PROS = [{"comment_ids": ["c1", "c2", "c3"], "aspect": "canh_quan", "text": "View biển đẹp"}]


class FakeCore:
    def __init__(self) -> None:
        self.saved: list[SaveSummaryRequest] = []
        self.previous: CoreSummary | None = None

    def fetch_post(self, post_id: str) -> CorePost:
        return CorePost(id=post_id, author_id="owner", title="Đà Nẵng", body="Phòng view biển")

    def fetch_summary(self, post_id: str) -> CoreSummary | None:
        return self.previous

    def fetch_comments(self, post_id: str) -> list[CoreComment]:
        now = datetime.now(UTC)
        return [
            CoreComment(
                id=f"c-{i}",
                author_id=f"u-{i}",
                body=text,
                created_at=now - timedelta(hours=i + 1),
                updated_at=now - timedelta(hours=i + 1),
            )
            for i, text in enumerate(TEXTS)
        ]

    def save_summary(self, post_id: str, request: SaveSummaryRequest) -> None:
        self.saved.append(request)


def _envelope(event_id: str, event_type: str = "content.comment.created") -> str:
    return json.dumps(
        {
            "eventId": event_id,
            "type": event_type,
            "version": 1,
            "occurredAt": "2026-11-05T08:00:00.000Z",
            "producer": "core-api",
            "payload": {"commentId": "c-9", "postId": POST, "authorId": "u-9", "body": "x"},
        }
    )


@pytest.fixture
def client() -> Iterator["redis.Redis"]:
    r = redis.Redis.from_url(cast(str, REDIS_URL), decode_responses=True)
    r.flushdb()
    yield r
    r.flushdb()


class Clock:
    def __init__(self) -> None:
        self.ms = 1_000_000

    def __call__(self) -> int:
        return self.ms


def _worker(r: "redis.Redis", core: FakeCore, clock: Clock, name: str = "a") -> sw.SummaryWorker:
    llm = FakeLlmClient(
        json.dumps(
            {
                "excluded": {"video_reaction_ids": [], "speculation_ids": []},
                "safety_mentions": [],
                "pros": PROS,
                "cons": [],
                "reality_gaps": [],
                "topics": [],
            }
        )
    )
    return sw.SummaryWorker(r, cast(CoreApiClient, core), llm, consumer_name=name, clock_ms=clock)


def _pending(r: "redis.Redis") -> int:
    return int(cast(dict[str, Any], r.xpending(sw.STREAM, sw.GROUP))["pending"])


def test_event_to_saved_summary_then_gap_then_same_hash(client: "redis.Redis") -> None:
    core, clock = FakeCore(), Clock()
    worker = _worker(client, core, clock)
    worker.ensure_group()
    worker.ensure_group()  # BUSYGROUP is fine

    client.xadd(sw.STREAM, {"event": _envelope("e1")})
    worker.poll_once()
    assert client.zscore(sw.DUE_KEY, POST) == clock.ms + sw.DEBOUNCE_MS
    assert _pending(client) == 0 and core.saved == []

    clock.ms += sw.DEBOUNCE_MS
    worker.poll_once()
    [saved] = core.saved
    assert saved.status == "ready" and saved.summary == "Khen: View biển đẹp."
    assert saved.safety is not None and saved.safety.warnings[0].comment_ids == ["c-5"]
    run_at = clock.ms

    client.xadd(sw.STREAM, {"event": _envelope("e2", "content.comment.updated")})
    clock.ms += 1_000
    worker.poll_once()
    assert client.zscore(sw.DUE_KEY, POST) == run_at + sw.MIN_GAP_MS
    assert 0 < cast(int, client.pttl(f"ai:summary:last_run:{POST}")) <= sw.MIN_GAP_MS

    core.previous = CoreSummary(status="ready", input_hash=saved.input_hash)
    clock.ms = run_at + sw.MIN_GAP_MS
    worker.poll_once()
    assert len(core.saved) == 1  # same input hash: nothing new saved


def test_bad_event_goes_to_dead_letter(client: "redis.Redis") -> None:
    worker = _worker(client, FakeCore(), Clock())
    worker.ensure_group()

    client.xadd(sw.STREAM, {"event": "not json"})
    worker.poll_once()

    [(_, fields)] = cast(list[tuple[str, dict[str, str]]], client.xrange(sw.DEAD_LETTER_STREAM))
    assert fields["group"] == sw.GROUP and _pending(client) == 0


def test_entry_left_by_a_dead_replica_is_claimed(
    client: "redis.Redis", monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = _worker(client, FakeCore(), Clock())
    worker.ensure_group()
    client.xadd(sw.STREAM, {"event": _envelope("e3")})
    client.xreadgroup(sw.GROUP, "dead", {sw.STREAM: ">"}, count=1)  # read, never acked
    monkeypatch.setattr(sw, "CLAIM_IDLE_MS", 0)

    worker.poll_once()

    assert _pending(client) == 0
    assert client.zscore(sw.DUE_KEY, POST) is not None


def test_two_replicas_never_run_the_same_post(client: "redis.Redis") -> None:
    clock = Clock()
    first, second = (_worker(client, FakeCore(), clock, n) for n in ("a", "b"))
    client.zadd(sw.DUE_KEY, {POST: clock.ms})

    assert first.scheduler.claim_due(clock.ms) == [POST]
    assert second.scheduler.claim_due(clock.ms) == []


def test_backfill_never_moves_a_live_run(client: "redis.Redis") -> None:
    scheduler = sw.SummaryScheduler(client)
    live_due = scheduler.schedule(POST, 1_000)

    assert scheduler.schedule_backfill(POST, 999_999) is False
    assert scheduler.schedule_backfill("other-post", 5_000) is True
    assert client.zscore(sw.DUE_KEY, POST) == live_due
    assert client.zscore(sw.DUE_KEY, "other-post") == 5_000
