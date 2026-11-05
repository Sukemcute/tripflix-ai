"""Summary worker: comment events in, one debounced summary run per post, result to core.

Agreed with content (Thành, 2026-11-05): tripflix-ai debounces and compares inputHash; core
stores the result. Run: `uv run python -m app.workers.summary_worker`.

Events: consumer group on `stream:core.content` (envelope v1, field "event"), same rules as
core's RedisStreamsConsumer: XACK after handling, XAUTOCLAIM entries idle > 60 s, dead-letter
after 5 deliveries or when the envelope cannot be read. Handling is idempotent (it only
reschedules), so a repeated delivery is harmless.

Timing (QT §3.1, rules unchanged, moved from a Postgres job table to Redis):
- debounce: run 60 s after the last comment event of a post;
- max wait: never later than 5 min after the first event of the batch (fix A2);
- min gap: 10 min between two runs of a post (fix A3);
- an event during a run schedules the next one (fix A1).
Redis keeps only timers with a TTL, no business data (RULES §10). Due posts sit in a sorted
set scored by due time (Redis delayed-queue pattern); ZREM decides which replica claims one.
"""

import logging
import os
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

import redis
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.alias_generators import to_camel

from app.clients.core_api import CoreApiClient
from app.clients.llm.base import LlmClient
from app.clients.llm.fake import FakeLlmClient
from app.core.config import Settings, get_settings
from app.services.summary.core_adapter import to_caption, to_comments, to_itinerary
from app.services.summary.pipeline import run_summary

logger = logging.getLogger(__name__)

STREAM = "stream:core.content"
DEAD_LETTER_STREAM = "stream:dead-letter"
GROUP = "ai-summary"
COMMENT_EVENTS = {"content.comment.created", "content.comment.updated", "content.comment.deleted"}

DEBOUNCE_MS = 60_000  # [HIỆU CHỈNH] QT §3.1
MAX_WAIT_MS = 300_000  # [HIỆU CHỈNH]
MIN_GAP_MS = 600_000  # [HIỆU CHỈNH]
TIMER_TTL_MS = MAX_WAIT_MS + MIN_GAP_MS  # timers expire on their own once useless

BATCH_SIZE = 20
BLOCK_MS = 1_000
CLAIM_IDLE_MS = 60_000
MAX_DELIVERIES = 5

DUE_KEY = "ai:summary:due"


def _first_key(post_id: str) -> str:
    return f"ai:summary:first:{post_id}"


def _last_run_key(post_id: str) -> str:
    return f"ai:summary:last_run:{post_id}"


def read_clock_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def next_due_ms(now_ms: int, first_event_ms: int, last_run_ms: int | None) -> int:
    due = min(now_ms + DEBOUNCE_MS, first_event_ms + MAX_WAIT_MS)
    return due if last_run_ms is None else max(due, last_run_ms + MIN_GAP_MS)


class _Envelope(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")
    event_id: str
    type: str
    version: int
    occurred_at: str
    producer: str
    trace_id: str | None = None
    user_id: str | None = None
    payload: dict[str, Any]


class _CommentPayload(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")
    comment_id: str
    post_id: str


class SummaryScheduler:
    def __init__(self, client: "redis.Redis") -> None:
        self.redis = client

    def schedule(self, post_id: str, now_ms: int) -> int:
        """Set or push back the post's run; returns the due time in ms."""
        self.redis.set(_first_key(post_id), now_ms, nx=True, px=TIMER_TTL_MS)
        first = int(cast(str, self.redis.get(_first_key(post_id))) or now_ms)
        last_run = cast(str | None, self.redis.get(_last_run_key(post_id)))
        due = next_due_ms(now_ms, first, int(last_run) if last_run else None)
        self.redis.zadd(DUE_KEY, {post_id: due})
        return due

    def schedule_backfill(self, post_id: str, due_ms: int) -> bool:
        """Add a run only if the post has none (ZADD NX): a live event's earlier run stays.

        Still honours the 10 min gap; returns False when a run was already scheduled.
        """
        last_run = cast(str | None, self.redis.get(_last_run_key(post_id)))
        if last_run:
            due_ms = max(due_ms, int(last_run) + MIN_GAP_MS)
        return bool(self.redis.zadd(DUE_KEY, {post_id: due_ms}, nx=True))

    def claim_due(self, now_ms: int, limit: int = BATCH_SIZE) -> list[str]:
        """Posts due now; only the replica whose ZREM removed the entry runs it."""
        due = cast(list[str], self.redis.zrangebyscore(DUE_KEY, "-inf", now_ms, start=0, num=limit))
        claimed: list[str] = []
        for post_id in due:
            if self.redis.zrem(DUE_KEY, post_id):
                # Mark the run now: events during it start a new batch after the min gap (A1).
                self.redis.set(_last_run_key(post_id), now_ms, px=MIN_GAP_MS)
                self.redis.delete(_first_key(post_id))
                claimed.append(post_id)
        return claimed


class SummaryWorker:
    def __init__(
        self,
        client: "redis.Redis",
        core: CoreApiClient,
        llm: LlmClient,
        *,
        is_llm_killed: bool = False,
        consumer_name: str | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.redis = client
        self.scheduler = SummaryScheduler(client)
        self.core = core
        self.llm = llm
        self.is_llm_killed = is_llm_killed
        self.consumer = consumer_name or f"{socket.gethostname()}-{os.getpid()}"
        self.clock_ms = clock_ms or read_clock_ms

    def ensure_group(self) -> None:
        """Read from the start of the stream so events sent while the worker was down count."""
        try:
            self.redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def poll_once(self) -> None:
        for message_id, fields in self._claim_stale():
            self.handle_entry(message_id, fields, self._delivery_count(message_id))
        for message_id, fields in self._read_new():
            self.handle_entry(message_id, fields, 1)
        for post_id in self.scheduler.claim_due(self.clock_ms()):
            self.summarize_post(post_id)

    def run_forever(self) -> None:
        self.ensure_group()
        logger.info("summary worker %s listening on %s", self.consumer, STREAM)
        while True:
            try:
                self.poll_once()
            except redis.ConnectionError:
                logger.exception("redis unavailable, retrying")
                self.redis.connection_pool.disconnect()

    def handle_entry(self, message_id: str, fields: dict[str, str], delivery_count: int) -> None:
        raw = fields.get("event", "")
        try:
            event = _Envelope.model_validate_json(raw)
            post_id = (
                _CommentPayload.model_validate(event.payload).post_id
                if event.type in COMMENT_EVENTS
                else None
            )
        except ValidationError as e:
            self._dead_letter(message_id, raw, f"unreadable event: {e.error_count()} errors")
            return
        if delivery_count > MAX_DELIVERIES:
            self._dead_letter(message_id, raw, f"delivered more than {MAX_DELIVERIES} times")
            return
        if post_id:
            self.scheduler.schedule(post_id, self.clock_ms())
        self.redis.xack(STREAM, GROUP, message_id)

    def summarize_post(self, post_id: str) -> None:
        try:
            self._summarize(post_id)
        except Exception:
            # Core or the LLM failed: try again after the min gap rather than lose the change.
            logger.exception("summary run failed for post %s", post_id)
            self.scheduler.schedule(post_id, self.clock_ms())

    def _summarize(self, post_id: str) -> None:
        post = self.core.fetch_post(post_id)
        if post is None:
            logger.info("post %s is gone or not public, skipped", post_id)
            return
        previous = self.core.fetch_summary(post_id)
        run = run_summary(
            comments=to_comments(self.core.fetch_comments(post_id), post.author_id),
            caption=to_caption(post),
            itinerary=to_itinerary(post),
            previous_hash=previous.input_hash if previous else None,
            now=datetime.fromtimestamp(self.clock_ms() / 1000, UTC),
            llm=self.llm,
            is_llm_killed=self.is_llm_killed,
        )
        if run.request is None:
            logger.info("post %s: same input as last summary, LLM not called", post_id)
            return
        if run.request.status == "failed" and previous and previous.status == "ready":
            # PUT overwrites the whole row: keep the last good summary on screen.
            logger.warning("post %s: run failed, previous summary kept", post_id)
            return
        self.core.save_summary(post_id, run.request)
        logger.info("post %s: summary saved with status %s", post_id, run.request.status)

    def _claim_stale(self) -> list[tuple[str, dict[str, str]]]:
        result = cast(
            list[Any],
            self.redis.xautoclaim(
                STREAM, GROUP, self.consumer, CLAIM_IDLE_MS, start_id="0-0", count=BATCH_SIZE
            ),
        )
        # Entries trimmed from the stream (MAXLEN) come back empty.
        return [(i, f) for i, f in result[1] if f]

    def _read_new(self) -> list[tuple[str, dict[str, str]]]:
        result = cast(
            list[Any] | None,
            self.redis.xreadgroup(
                GROUP, self.consumer, {STREAM: ">"}, count=BATCH_SIZE, block=BLOCK_MS
            ),
        )
        return [entry for _, entries in result or [] for entry in entries]

    def _delivery_count(self, message_id: str) -> int:
        rows = cast(
            list[dict[str, Any]],
            self.redis.xpending_range(STREAM, GROUP, min=message_id, max=message_id, count=1),
        )
        return int(rows[0]["times_delivered"]) if rows else 1

    def _dead_letter(self, message_id: str, raw: str, reason: str) -> None:
        logger.warning("event %s to dead-letter: %s", message_id, reason)
        self.redis.xadd(
            DEAD_LETTER_STREAM,
            {
                "event": raw,
                "stream": STREAM,
                "group": GROUP,
                "messageId": message_id,
                "reason": reason,
            },
        )
        self.redis.xack(STREAM, GROUP, message_id)


def build_llm(settings: Settings) -> LlmClient:
    if settings.llm_provider == "fake":
        return FakeLlmClient()
    raise NotImplementedError(f"LLM provider {settings.llm_provider!r} is not chosen yet (P9)")


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    worker = SummaryWorker(
        redis.Redis.from_url(settings.redis_url, decode_responses=True),
        CoreApiClient(
            settings.core_api_url, settings.service_client_id, settings.service_client_secret
        ),
        build_llm(settings),
        is_llm_killed=settings.summary_llm_kill,
    )
    worker.run_forever()


if __name__ == "__main__":
    main()
