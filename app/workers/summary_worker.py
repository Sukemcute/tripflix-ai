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

When something breaks (research note 04 §3):
- a claimed post sits in an in-flight set with a lease; a worker that dies mid-run leaves it
  there and the next poll of any replica puts it back once the lease is over;
- a failed run is retried with exponential backoff (fixed per-post jitter), at most
  MAX_RUN_ATTEMPTS times, then the post goes to the dead-letter stream; a 400/413/422 from
  core goes there at once (retrying cannot fix the request);
- the LLM and the classifier sit behind circuit breakers: an open LLM breaker puts the post
  back for when it closes without spending an attempt; a failing classifier means rules;
- one post per loop, so events (a hide's 60 s run) are read between two runs.

Input and recovery (Thành, PR be #128, 2026-11-11):
- a run reads core's seeded random sample (SAMPLE_SIZE) with whole-post counts, one request
  instead of up to 50 pages of the newest comments; an older core without the route means
  the newest pages again, without whole-post counts;
"""

import logging
import os
import socket
import threading
import time
import zlib
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import redis
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic.alias_generators import to_camel

from app.clients.core_api import CoreApiClient, SampleUnavailableError
from app.clients.llm.anthropic import AnthropicLlmClient
from app.clients.llm.base import LlmClient
from app.clients.llm.deepseek import DeepSeekClient
from app.clients.llm.fake import FakeLlmClient
from app.clients.llm.guarded import GuardedLlmClient, LlmUnavailableError
from app.clients.llm.openai import OpenAILlmClient
from app.core.breaker import CircuitBreaker
from app.core.config import Settings, get_settings
from app.services.summary.comment_classifier import (
    CommentClassifier,
    CommentLabels,
    GuardedClassifier,
    load_comment_classifier,
)
from app.services.summary.core_adapter import (
    build_caption,
    build_itinerary,
    convert_comments,
    convert_sample,
)
from app.services.summary.estimates import PostStats
from app.services.summary.label_store import (
    LabelStore,
    RedisLabelStore,
    StoredLabel,
    StoredSafety,
    content_hash,
    fresh_labels,
)
from app.services.summary.pipeline import CLASSIFIER_MAX_COMMENTS, run_summary
from app.services.summary.schemas import CommentIn

logger = logging.getLogger(__name__)

STREAM = "stream:core.content"
DEAD_LETTER_STREAM = "stream:dead-letter"
GROUP = "ai-summary"
COMMENT_EVENTS = {
    "content.comment.created",
    "content.comment.updated",
    "content.comment.deleted",
    # moderation (Trang, 2026-11-09): one event per comment whose visibility changed
    "content.comment.hidden",
    "content.comment.restored",
}
# Core holds the summary back while one of its sources is hidden or deleted (Trang, 2026-11-09),
# so these run within the debounce instead of waiting for the min gap.
HELD_EVENTS = {"content.comment.hidden", "content.comment.deleted"}

DEBOUNCE_MS = 60_000  # [HIỆU CHỈNH] QT §3.1
MAX_WAIT_MS = 300_000  # [HIỆU CHỈNH]
MIN_GAP_MS = 600_000  # [HIỆU CHỈNH]
TIMER_TTL_MS = MAX_WAIT_MS + MIN_GAP_MS  # timers expire on their own once useless

BATCH_SIZE = 20
BLOCK_MS = 1_000
IDLE_SECONDS = 0.5  # job loop pause when nothing is due
CLAIM_IDLE_MS = 60_000
MAX_DELIVERIES = 5

# Longer than a worst run: classifier cap ~25 s + LLM 3 x 30 s + core reads.
LEASE_MS = 300_000  # [HIỆU CHỈNH]
MAX_RUN_ATTEMPTS = 5  # 1, 2, 4, 8 min between them: ~15 min of retries, then dead-letter
RETRY_BASE_MS = 60_000
RETRY_CAP_MS = 1_800_000
RETRY_JITTER_MS = 10_000
ATTEMPTS_TTL_MS = 86_400_000
PERMANENT_STATUSES = {400, 413, 422}  # core rejects the request itself: retrying cannot help

# Cochran: about 2,400 writers give a share within +-2% at 95%, whatever the post size;
# 3,000 comments use ~30 MB in the worker. [HIỆU CHỈNH]
SAMPLE_SIZE = 3_000
DUE_KEY = "ai:summary:due"
INFLIGHT_KEY = "ai:summary:inflight"


def _first_key(post_id: str) -> str:
    return f"ai:summary:first:{post_id}"


def _last_run_key(post_id: str) -> str:
    return f"ai:summary:last_run:{post_id}"


def _held_key(post_id: str) -> str:
    return f"ai:summary:held:{post_id}"


def _attempts_key(post_id: str) -> str:
    return f"ai:summary:attempts:{post_id}"


class RunFailedError(Exception):
    """The LLM answered but its output could not be trusted: worth another try later."""


def compute_retry_delay_ms(attempt: int, post_id: str) -> int:
    """Exponential backoff with a fixed per-post offset (AWS prefers it to random jitter for
    scheduled work: posts failing together do not retry together, and it is easy to trace)."""
    backoff = min(RETRY_BASE_MS * 2 ** (attempt - 1), RETRY_CAP_MS)
    return backoff + zlib.crc32(post_id.encode()) % RETRY_JITTER_MS


def read_clock_ms() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def compute_next_due_ms(now_ms: int, first_event_ms: int, last_run_ms: int | None) -> int:
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
        due = compute_next_due_ms(now_ms, first, int(last_run) if last_run else None)
        held_due = cast(str | None, self.redis.get(_held_key(post_id)))
        if held_due:  # later events never push a hide's or delete's run back
            due = min(due, int(held_due))
        self.redis.zadd(DUE_KEY, {post_id: due})
        return due

    def schedule_held(self, post_id: str, now_ms: int) -> int:
        """A hide or delete runs within the debounce of the first one, skipping the min gap."""
        self.redis.set(_held_key(post_id), now_ms + DEBOUNCE_MS, nx=True, px=TIMER_TTL_MS)
        return self.schedule(post_id, now_ms)

    def schedule_backfill(self, post_id: str, due_ms: int) -> bool:
        """Add a run only if the post has none (ZADD NX): a live event's earlier run stays.

        Still honours the 10 min gap; returns False when a run was already scheduled.
        """
        last_run = cast(str | None, self.redis.get(_last_run_key(post_id)))
        if last_run:
            due_ms = max(due_ms, int(last_run) + MIN_GAP_MS)
        return bool(self.redis.zadd(DUE_KEY, {post_id: due_ms}, nx=True))

    def claim_due(self, now_ms: int, limit: int = BATCH_SIZE) -> list[str]:
        """Posts due now; only the replica whose ZREM removed the entry runs it.

        A claimed post gets a lease in the in-flight set until finish(). shortcut: ZREM and
        ZADD are two commands, so a crash exactly between them loses the post; a Lua script
        makes it atomic if that ever shows up (backfill recovers it meanwhile).
        """
        due = cast(list[str], self.redis.zrangebyscore(DUE_KEY, "-inf", now_ms, start=0, num=limit))
        claimed: list[str] = []
        for post_id in due:
            if self.redis.zrem(DUE_KEY, post_id):
                self.redis.zadd(INFLIGHT_KEY, {post_id: now_ms + LEASE_MS})
                # Mark the run now: events during it start a new batch after the min gap (A1).
                self.redis.set(_last_run_key(post_id), now_ms, px=MIN_GAP_MS)
                self.redis.delete(_first_key(post_id))
                self.redis.delete(_held_key(post_id))
                claimed.append(post_id)
        return claimed

    def finish(self, post_id: str) -> None:
        self.redis.zrem(INFLIGHT_KEY, post_id)

    def reclaim_expired(self, now_ms: int) -> list[str]:
        """Posts whose worker died mid-run (lease over): due again now, earlier runs kept."""
        expired = cast(
            list[str],
            self.redis.zrangebyscore(INFLIGHT_KEY, "-inf", now_ms, start=0, num=BATCH_SIZE),
        )
        back = [p for p in expired if self.redis.zrem(INFLIGHT_KEY, p)]
        for post_id in back:
            logger.warning("post %s: lease expired, run again", post_id)
            self.redis.zadd(DUE_KEY, {post_id: now_ms}, lt=True)
        return back

    def start_attempt(self, post_id: str) -> int:
        """Count the attempt when the run starts, not when it fails: a run that kills the
        process (out of memory) raises nothing, so counting on failure looped it forever."""
        attempt = int(cast(int, self.redis.incr(_attempts_key(post_id))))
        self.redis.pexpire(_attempts_key(post_id), ATTEMPTS_TTL_MS)
        return attempt

    def retry(self, post_id: str, now_ms: int, attempt: int) -> int | None:
        """Due time of the next attempt, or None when the post is out of attempts."""
        if attempt >= MAX_RUN_ATTEMPTS:
            return None
        due = now_ms + compute_retry_delay_ms(attempt, post_id)
        self.redis.zadd(DUE_KEY, {post_id: due}, lt=True)  # an earlier event-driven run stays
        return due

    def defer(self, post_id: str, due_ms: int) -> None:
        """Run later without spending an attempt (the LLM breaker is open)."""
        self.redis.decr(_attempts_key(post_id))
        self.redis.zadd(DUE_KEY, {post_id: due_ms}, lt=True)

    def clear_attempts(self, post_id: str) -> None:
        self.redis.delete(_attempts_key(post_id))


class SummaryWorker:
    def __init__(
        self,
        client: "redis.Redis",
        core: CoreApiClient,
        llm: LlmClient,
        *,
        is_llm_killed: bool = False,
        classifier: CommentClassifier | None = None,
        classifier_max_comments: int = CLASSIFIER_MAX_COMMENTS,
        label_store: LabelStore | None = None,
        consumer_name: str | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self.redis = client
        self.scheduler = SummaryScheduler(client)
        self.core = core
        self.llm = llm
        self.is_llm_killed = is_llm_killed
        self.classifier = classifier
        self.classifier_max_comments = classifier_max_comments
        self.label_store = label_store
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
        self.poll_events_once()
        self.run_jobs_once()

    def poll_events_once(self) -> None:
        for message_id, fields in self._claim_stale():
            self.handle_entry(message_id, fields, self._delivery_count(message_id))
        for message_id, fields in self._read_new():
            self.handle_entry(message_id, fields, 1)

    def run_jobs_once(self) -> bool:
        """Run at most one due post; False when none was due."""
        self.scheduler.reclaim_expired(self.clock_ms())
        claimed = self.scheduler.claim_due(self.clock_ms(), limit=1)
        for post_id in claimed:
            self.summarize_post(post_id)
        return bool(claimed)

    def run_forever(self) -> None:
        """Events and runs on two threads: a 30 s run no longer stops the stream from being
        read, so events are scheduled (and acked) before core trims them (MAXLEN ~100k)."""
        self.ensure_group()
        logger.info("summary worker %s listening on %s", self.consumer, STREAM)
        threading.Thread(
            target=self._loop, args=(self.poll_events_once,), name="events", daemon=True
        ).start()
        self._loop(lambda: self.run_jobs_once() or time.sleep(IDLE_SECONDS))

    def _loop(self, step: Callable[[], object]) -> None:
        while True:
            try:
                step()
            except redis.ConnectionError:
                logger.exception("redis unavailable, retrying")
                self.redis.connection_pool.disconnect()
                time.sleep(IDLE_SECONDS)
            except Exception:
                # A bug in one loop must not kill the other one (or the process) silently.
                logger.exception("worker loop error, continuing")
                time.sleep(IDLE_SECONDS)

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
        if post_id and event.type in HELD_EVENTS:
            self.scheduler.schedule_held(post_id, self.clock_ms())
        elif post_id:
            self.scheduler.schedule(post_id, self.clock_ms())
        self.redis.xack(STREAM, GROUP, message_id)

    def summarize_post(self, post_id: str) -> None:
        attempt = self.scheduler.start_attempt(post_id)
        if attempt > MAX_RUN_ATTEMPTS:
            # Earlier runs died without an error (a poison post): stop before it kills us again.
            logger.error("post %s started %s times without finishing", post_id, attempt - 1)
            self._give_up(post_id, f"started {attempt - 1} times without finishing")
            self.scheduler.finish(post_id)
            return
        try:
            self._summarize(post_id)
        except LlmUnavailableError as e:
            logger.warning("post %s: %s", post_id, e)
            self.scheduler.defer(post_id, self.clock_ms() + int(e.retry_in_seconds * 1000))
        except Exception as e:
            if _is_permanent(e):
                logger.exception("summary run for post %s cannot succeed", post_id)
                self._give_up(post_id, f"permanent error: {type(e).__name__} {e}")
            elif (due := self.scheduler.retry(post_id, self.clock_ms(), attempt)) is None:
                logger.exception("summary run for post %s failed for the last time", post_id)
                self._give_up(post_id, f"failed {MAX_RUN_ATTEMPTS} times: {type(e).__name__} {e}")
            else:
                logger.exception("summary run failed for post %s, retry at %s", post_id, due)
        else:
            self.scheduler.clear_attempts(post_id)
        finally:
            self.scheduler.finish(post_id)

    def _give_up(self, post_id: str, reason: str) -> None:
        """Out of the queue, into the dead-letter stream; backfill or a new event retries it."""
        self.scheduler.clear_attempts(post_id)
        self.redis.xadd(
            DEAD_LETTER_STREAM,
            {"postId": post_id, "group": GROUP, "reason": reason[:500]},
        )

    def _summarize(self, post_id: str) -> None:
        # generatedAt: before any input is read, so a run that read older comments always loses
        # to a later one in core's write, however long its LLM call takes (Trang, 2026-11-09).
        started = datetime.fromtimestamp(self.clock_ms() / 1000, UTC)
        post = self.core.fetch_post(post_id)
        if post is None:
            logger.info("post %s is gone or not public, skipped", post_id)
            return
        previous = self.core.fetch_summary(post_id)
        # A row saved before sourceCommentIds has unknown sources: core cannot tell whether a
        # hidden comment is in it, so regenerate it once rather than let the same hash skip it.
        is_known = previous is not None and previous.source_comment_ids is not None
        comments, stats = self._read_comments(post_id, post.author_id)
        run = run_summary(
            comments=comments,
            caption=build_caption(post),
            itinerary=build_itinerary(post),
            previous_hash=previous.input_hash if previous and is_known else None,
            now=started,
            llm=self.llm,
            is_llm_killed=self.is_llm_killed,
            classifier=self.classifier,
            classifier_max_comments=self.classifier_max_comments,
            known_labels=self._stored_labels(post_id, comments),
            post_stats=stats,
            known_safety=self._kept_safety(post_id),
        )
        self._keep_labels(post_id, comments, run.new_labels)
        if run.request is None:
            logger.info("post %s: same input as last summary, LLM not called", post_id)
            return
        is_failed = run.request.status == "failed"
        if is_failed and previous and previous.status == "ready":
            # PUT overwrites the whole row: keep the last good summary on screen.
            logger.warning("post %s: run failed, previous summary kept", post_id)
        else:
            self.core.save_summary(post_id, run.request)
            labeler = run.request.content.labeler if run.request.content else "none"
            logger.info(
                "post %s: summary saved with status %s, labeler %s",
                post_id,
                run.request.status,
                labeler,
            )
        # Retry, or a post whose source was hidden stays held back until its next event.
        # The kill switch is on purpose: run backfill once it is off.
        if is_failed and not self.is_llm_killed:
            raise RunFailedError(f"post {post_id}: LLM output could not be trusted")

    def _stored_labels(self, post_id: str, comments: list[CommentIn]) -> dict[str, CommentLabels]:
        """Labels made earlier (label worker or past runs) that still match text and model.
        The store failing costs only time: the run labels everything itself, as before."""
        if self.label_store is None or self.classifier is None:
            return {}
        bodies = {c.comment_id: c.body for c in comments if c.status == "visible"}
        try:
            stored = self.label_store.get_many(post_id, bodies)
        except Exception:
            logger.exception("post %s: label store unreadable, labelling from scratch", post_id)
            return {}
        return fresh_labels(stored, bodies, self.classifier.version)

    def _read_comments(
        self, post_id: str, post_author_id: str
    ) -> tuple[list[CommentIn], PostStats | None]:
        """Core's random sample and its whole-post counts; the newest pages on an older core."""
        try:
            sample = self.core.fetch_comment_sample(post_id, SAMPLE_SIZE, seed=post_id)
        except SampleUnavailableError as e:
            logger.warning("post %s: no sample route (%s), reading the newest pages", post_id, e)
            return convert_comments(self.core.fetch_comments(post_id), post_author_id), None
        stats = PostStats(sample.stats.visible_comment_count, sample.stats.unique_author_count)
        return convert_sample(sample.items, post_author_id), stats

    def _kept_safety(self, post_id: str) -> list[StoredSafety]:
        """Safety results the label worker kept; unreadable means the sample's own only."""
        if self.label_store is None:
            return []
        try:
            return self.label_store.get_safety(post_id)
        except Exception:
            logger.exception("post %s: kept safety results unreadable", post_id)
            return []

    def _keep_labels(
        self, post_id: str, comments: list[CommentIn], labels: Mapping[str, CommentLabels]
    ) -> None:
        if self.label_store is None or self.classifier is None or not labels:
            return
        by_id = {c.comment_id: c for c in comments}
        try:
            for cid, label in labels.items():
                c = by_id[cid]
                stored = StoredLabel(label, self.classifier.version, content_hash(c.body))
                self.label_store.put(post_id, cid, c.author_id, stored)
        except Exception:
            logger.exception("post %s: labels not kept, the next run labels them again", post_id)

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


def _is_permanent(error: Exception) -> bool:
    return (
        isinstance(error, httpx.HTTPStatusError)
        and error.response.status_code in PERMANENT_STATUSES
    )


def build_llm(settings: Settings) -> LlmClient:
    """The one place that knows the providers: everything else sees the LlmClient port."""
    limits = {
        "timeout_seconds": settings.llm_timeout_seconds,
        "max_output_tokens": settings.llm_max_output_tokens,
    }
    prices = {
        name: value
        for name, value in (
            ("input", settings.llm_price_input),
            ("cached_input", settings.llm_price_cached_input),
            ("output", settings.llm_price_output),
        )
        if value is not None
    }
    if settings.llm_provider == "fake":
        return FakeLlmClient()
    if settings.llm_provider == "openai":
        if len(prices) < 3:
            raise ValueError(
                "openai needs LLM_PRICE_INPUT, LLM_PRICE_CACHED_INPUT, LLM_PRICE_OUTPUT"
            )
        return OpenAILlmClient(
            settings.openai_api_key,
            model=settings.llm_model,
            prices=prices,
            base_url=settings.openai_base_url,
            reasoning_effort=settings.openai_reasoning_effort,
            **limits,
        )
    if settings.llm_provider == "anthropic":
        return AnthropicLlmClient(
            settings.anthropic_api_key, model=settings.llm_model, prices=prices, **limits
        )
    return DeepSeekClient(
        settings.deepseek_api_key,
        model=settings.llm_model,
        base_url=settings.deepseek_base_url,
        **limits,
    )


def build_classifier(settings: Settings) -> CommentClassifier | None:
    if not settings.is_classifier_enabled:
        logger.info("comment classifier switched off (CLASSIFIER_ENABLED=false), rules used")
        return None
    loaded = load_comment_classifier(
        settings.classifier_dir, settings.classifier_threads, settings.classifier_batch
    )
    return GuardedClassifier(loaded, CircuitBreaker("classifier")) if loaded else None


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    worker = SummaryWorker(
        client,
        CoreApiClient(
            settings.core_api_url, settings.service_client_id, settings.service_client_secret
        ),
        GuardedLlmClient(build_llm(settings), CircuitBreaker("llm")),
        is_llm_killed=settings.is_summary_llm_killed,
        classifier=build_classifier(settings),
        classifier_max_comments=settings.classifier_max_comments,
        label_store=RedisLabelStore(client),
    )
    worker.run_forever()


if __name__ == "__main__":
    main()
