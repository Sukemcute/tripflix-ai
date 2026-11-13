import json
from datetime import UTC, datetime
from typing import Any, cast

import httpx
import pytest

from app.clients.core_api import CoreApiClient, CorePost, CoreSummary, SampleUnavailableError
from app.clients.llm.fake import FakeLlmClient
from app.clients.llm.guarded import LlmUnavailableError
from app.core.breaker import CircuitBreaker
from app.services.summary.pipeline import SummaryRun
from app.services.summary.schemas import SaveSummaryRequest
from app.workers import summary_worker
from app.workers.summary_worker import (
    DEBOUNCE_MS,
    DUE_KEY,
    INFLIGHT_KEY,
    LEASE_MS,
    MAX_RUN_ATTEMPTS,
    MAX_WAIT_MS,
    MIN_GAP_MS,
    SummaryScheduler,
    SummaryWorker,
    compute_next_due_ms,
    compute_retry_delay_ms,
)

POST = "018d9f20-0000-7000-8000-000000000001"


class FakeRedis:
    """The few Redis commands the scheduler and handler use; TTLs are ignored."""

    def __init__(self) -> None:
        self.ttl: dict[str, int | None] = {}
        self.kv: dict[str, str] = {}
        self.zsets: dict[str, dict[str, float]] = {}
        self.acked: list[str] = []
        self.dead: list[dict[str, str]] = []

    @property
    def zset(self) -> dict[str, float]:  # the due queue, what most tests look at
        return self.zsets.setdefault(DUE_KEY, {})

    @property
    def inflight(self) -> dict[str, float]:
        return self.zsets.setdefault(INFLIGHT_KEY, {})

    def set(self, key: str, value: object, nx: bool = False, px: int | None = None) -> bool:
        if nx and key in self.kv:
            return False
        self.kv[key] = str(value)
        self.ttl[key] = px
        return True

    def get(self, key: str) -> str | None:
        return self.kv.get(key)

    def delete(self, key: str) -> int:
        return int(self.kv.pop(key, None) is not None)

    def incr(self, key: str) -> int:
        self.kv[key] = str(int(self.kv.get(key, "0")) + 1)
        return int(self.kv[key])

    def decr(self, key: str) -> int:
        self.kv[key] = str(int(self.kv.get(key, "0")) - 1)
        return int(self.kv[key])

    def pexpire(self, key: str, ms: int) -> bool:
        return key in self.kv

    def zadd(self, key: str, mapping: dict[str, float], nx: bool = False, lt: bool = False) -> int:
        zset = self.zsets.setdefault(key, {})
        added = 0
        for member, score in mapping.items():
            if member in zset and (nx or (lt and score >= zset[member])):
                continue
            added += member not in zset
            zset[member] = score
        return added

    def zrangebyscore(self, key: str, low: str, high: float, start: int, num: int) -> list[str]:
        ready = sorted((s, m) for m, s in self.zsets.get(key, {}).items() if s <= high)
        return [m for _, m in ready][start : start + num]

    def zrem(self, key: str, member: str) -> int:
        return int(self.zsets.get(key, {}).pop(member, None) is not None)

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


def test_a_hide_skips_the_min_gap_and_later_events_never_push_it_back() -> None:
    """Core holds the summary back after a hide, so the new one must come within a minute."""
    redis = FakeRedis()
    scheduler = SummaryScheduler(cast(Any, redis))
    scheduler.schedule(POST, 0)
    assert scheduler.claim_due(DEBOUNCE_MS) == [POST]  # a run just happened

    hide_at = DEBOUNCE_MS + 1_000
    assert scheduler.schedule_held(POST, hide_at) == hide_at + DEBOUNCE_MS  # no 10 min wait
    assert scheduler.schedule_held(POST, hide_at + 30_000) == hide_at + DEBOUNCE_MS  # cascade
    assert scheduler.schedule(POST, hide_at + 50_000) == hide_at + DEBOUNCE_MS  # a new comment
    assert scheduler.claim_due(hide_at + DEBOUNCE_MS) == [POST]

    # Once that run is claimed, ordinary comments wait for the min gap again.
    after = hide_at + DEBOUNCE_MS + 1_000
    assert scheduler.schedule(POST, after) == hide_at + DEBOUNCE_MS + MIN_GAP_MS


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

    def fetch_comment_sample(self, post_id: str, size: int, seed: str) -> Any:
        raise SampleUnavailableError("core answered 404")  # an older core: the flat pages

    def iter_held_summaries(self) -> list[str]:
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


@pytest.mark.parametrize("event_type", ["content.comment.hidden", "content.comment.restored"])
def test_moderation_hide_and_restore_reschedule_the_post(event_type: str) -> None:
    """Payload agreed with Trang and Thành (2026-11-09); a repeat only reschedules the post."""
    redis = FakeRedis()
    worker = _worker(redis, FakeCoreApi())

    worker.handle_entry("1-0", _event(event_type, authorId="u-7"), 1)
    worker.handle_entry("2-0", _event(event_type, authorId="u-7"), 1)  # delivered twice

    assert list(redis.zset) == [POST] and redis.acked == ["1-0", "2-0"]
    # Only a hide takes the fast lane: a restore waits like any other change.
    is_fast = f"ai:summary:held:{POST}" in redis.kv
    assert is_fast == (event_type == "content.comment.hidden")


@pytest.mark.parametrize(
    ("event_type", "is_fast"),
    [
        ("content.comment.hidden", True),
        ("content.comment.deleted", True),  # core holds a summary back for deleted sources too
        ("content.comment.created", False),
        ("content.comment.updated", False),
        ("content.comment.restored", False),
    ],
)
def test_only_events_that_make_core_hold_the_summary_skip_the_min_gap(
    event_type: str, is_fast: bool
) -> None:
    redis = FakeRedis()
    worker = _worker(redis, FakeCoreApi())
    redis.kv[f"ai:summary:last_run:{POST}"] = "0"  # a run just happened at t=0

    worker.handle_entry("1-0", _event(event_type), 1)

    expected = 1_000 + DEBOUNCE_MS if is_fast else MIN_GAP_MS
    assert redis.zset[POST] == expected


def test_other_event_types_are_acked_and_ignored() -> None:
    redis = FakeRedis()

    _worker(redis, FakeCoreApi()).handle_entry("1-0", _event("content.media.ready"), 1)

    assert redis.acked == ["1-0"] and not redis.zset


def test_run_saves_the_result_to_core() -> None:
    core = FakeCoreApi()

    _worker(FakeRedis(), core).summarize_post(POST)

    assert [r.status for r in core.saved] == ["no_comments"]


def test_generated_at_is_when_the_run_started_reading() -> None:
    """A slow run must not look newer than a run that read the comments after it."""
    clock = {"ms": 1_000}

    class SlowCore(FakeCoreApi):
        def fetch_comments(self, post_id: str) -> list[Any]:
            clock["ms"] = 90_000  # reading and the LLM take time
            return []

    core = SlowCore()
    worker = SummaryWorker(
        cast(Any, FakeRedis()),
        cast(CoreApiClient, core),
        FakeLlmClient(),
        consumer_name="test",
        clock_ms=lambda: clock["ms"],
    )

    worker.summarize_post(POST)

    assert core.saved[0].generated_at == datetime.fromtimestamp(1, UTC)


@pytest.mark.parametrize(
    ("sources", "previous_hash"),
    [(None, None), (["c1"], "h")],  # unknown sources: regenerate once despite the same hash
)
def test_a_summary_without_sources_is_regenerated_once(
    monkeypatch: pytest.MonkeyPatch, sources: list[str] | None, previous_hash: str | None
) -> None:
    seen: list[str | None] = []

    def fake_run(**kwargs: Any) -> SummaryRun:
        seen.append(kwargs["previous_hash"])
        return SummaryRun(None)

    monkeypatch.setattr(summary_worker, "run_summary", fake_run)
    previous = CoreSummary(status="ready", input_hash="h", source_comment_ids=sources)

    _worker(FakeRedis(), FakeCoreApi(previous=previous)).summarize_post(POST)

    assert seen == [previous_hash]


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


# --- When things break (TF44): lease, bounded retry, dead-letter, breaker ---


class FailingCore(FakeCoreApi):
    def __init__(self, error: Exception, previous: CoreSummary | None = None) -> None:
        super().__init__(previous=previous)
        self.error = error

    def fetch_comments(self, post_id: str) -> list[Any]:
        raise self.error


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("PUT", "http://core/api")
    response = httpx.Response(status, request=request)
    return httpx.HTTPStatusError("core said no", request=request, response=response)


def test_a_worker_that_dies_mid_run_leaves_the_post_for_the_next_one() -> None:
    redis = FakeRedis()
    first = SummaryScheduler(cast(Any, redis))
    first.schedule(POST, 0)
    assert first.claim_due(DEBOUNCE_MS) == [POST]  # ...then the process is killed, no finish()

    second = SummaryScheduler(cast(Any, redis))
    assert second.reclaim_expired(DEBOUNCE_MS + LEASE_MS - 1) == []  # lease still running
    assert second.reclaim_expired(DEBOUNCE_MS + LEASE_MS) == [POST]
    assert second.claim_due(DEBOUNCE_MS + LEASE_MS) == [POST]


def test_a_finished_run_gives_its_lease_back() -> None:
    redis = FakeRedis()
    scheduler = SummaryScheduler(cast(Any, redis))
    scheduler.schedule(POST, 0)
    [post] = scheduler.claim_due(DEBOUNCE_MS)
    assert post in redis.inflight

    _worker(redis, FakeCoreApi()).summarize_post(post)

    assert redis.inflight == {} and POST not in redis.zset


def test_failures_back_off_then_go_to_dead_letter() -> None:
    redis = FakeRedis()
    worker = _worker(redis, FailingCore(RuntimeError("core down")))
    delays: list[float] = []

    for _ in range(MAX_RUN_ATTEMPTS - 1):
        worker.summarize_post(POST)
        delays.append(redis.zset.pop(POST) - 1_000)  # taken off as if it ran again
    worker.summarize_post(POST)

    assert delays == sorted(delays) and delays[0] >= 60_000  # 1, 2, 4, 8 min + fixed jitter
    assert POST not in redis.zset and redis.inflight == {}
    assert redis.dead[-1]["postId"] == POST
    assert f"failed {MAX_RUN_ATTEMPTS} times" in redis.dead[-1]["reason"]
    assert f"ai:summary:attempts:{POST}" not in redis.kv


def test_a_request_core_rejects_goes_to_dead_letter_at_once() -> None:
    redis = FakeRedis()

    _worker(redis, FailingCore(_http_error(422))).summarize_post(POST)

    assert POST not in redis.zset and "permanent" in redis.dead[-1]["reason"]


def test_a_401_is_retried_not_dead_lettered() -> None:
    """A token or key rotation on core heals on its own within minutes."""
    redis = FakeRedis()

    _worker(redis, FailingCore(_http_error(401))).summarize_post(POST)

    assert POST in redis.zset and redis.dead == []


def test_a_retry_never_pushes_back_an_earlier_event_run() -> None:
    redis = FakeRedis()
    redis.zset[POST] = 5_000  # a hide during the run asked for an early run

    _worker(redis, FailingCore(RuntimeError("core down"))).summarize_post(POST)

    assert redis.zset[POST] == 5_000


def test_retry_delay_is_fixed_per_post_and_capped() -> None:
    assert compute_retry_delay_ms(1, POST) == compute_retry_delay_ms(1, POST)
    assert compute_retry_delay_ms(30, POST) < 1_800_000 + 10_000


@pytest.mark.parametrize("is_killed", [False, True])
def test_an_untrusted_llm_output_is_retried_unless_the_kill_switch_is_on(
    monkeypatch: pytest.MonkeyPatch, is_killed: bool
) -> None:
    """Without the retry, a summary held back for a hidden source stays hidden until the next
    event; with the kill switch on, the operator runs backfill once it is off."""
    redis = FakeRedis()
    core = FakeCoreApi(previous=CoreSummary(status="ready", input_hash="h"))
    failed = SaveSummaryRequest(status="failed", generated_at=datetime(2026, 11, 5, tzinfo=UTC))
    monkeypatch.setattr(summary_worker, "run_summary", lambda **_: SummaryRun(failed))  # pyright: ignore[reportUnknownLambdaType]
    worker = _worker(redis, core)
    worker.is_llm_killed = is_killed

    worker.summarize_post(POST)

    assert core.saved == []  # the ready summary stays on screen
    assert (POST in redis.zset) is not is_killed


def test_an_open_llm_breaker_waits_without_spending_an_attempt() -> None:
    redis = FakeRedis()
    breaker = CircuitBreaker("llm", threshold=1, open_seconds=120, clock=lambda: 0.0)
    breaker.record_failure()

    _worker(redis, FailingCore(LlmUnavailableError(breaker.seconds_left()))).summarize_post(POST)

    assert redis.zset[POST] == 1_000 + 120_000
    assert redis.kv.get(f"ai:summary:attempts:{POST}", "0") == "0" and redis.dead == []


def test_the_job_loop_never_touches_the_stream() -> None:
    """Runs and events live on separate threads: FakeRedis has no stream commands, so a job
    loop that read events would fail here."""
    redis = FakeRedis()
    core = FakeCoreApi()
    worker = _worker(redis, core)
    redis.zset[POST] = 0

    assert worker.run_jobs_once() is True
    assert worker.run_jobs_once() is False  # nothing due any more
    assert [r.status for r in core.saved] == ["no_comments"]


def test_a_post_that_keeps_killing_the_worker_goes_to_dead_letter() -> None:
    """Out of memory raises nothing: each run started but never finished. The 6th start
    gives up instead of loading the post again."""
    redis = FakeRedis()
    core = FakeCoreApi()
    redis.kv[f"ai:summary:attempts:{POST}"] = str(MAX_RUN_ATTEMPTS)  # 5 starts that died

    _worker(redis, core).summarize_post(POST)

    assert core.saved == [] and "started 5 times" in redis.dead[-1]["reason"]
    assert redis.inflight == {} and f"ai:summary:attempts:{POST}" not in redis.kv


class _Classifier:
    version = "v1"

    def classify(self, pairs: Any) -> list[Any]:
        return []


class _Store:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.kept: list[str] = []

    def get_many(self, post_id: str, comment_ids: Any) -> dict[str, Any]:
        if self.error:
            raise self.error
        from app.services.summary.label_store import StoredLabel, content_hash

        return {"c1": StoredLabel(_LABEL, "v1", content_hash("Phòng sạch"))}

    def put(self, post_id: str, comment_id: str, author_id: str, label: Any) -> None:
        self.kept.append(comment_id)

    def remove(self, post_id: str, comment_id: str) -> None:
        pass

    def put_safety(self, post_id: str, hit: Any) -> None:
        pass

    def get_safety(self, post_id: str) -> list[Any]:
        if self.error:
            raise self.error
        return []


from app.services.summary.comment_classifier import CommentLabels  # noqa: E402

_LABEL = CommentLabels(True, True, False, False, True, False)


class _CoreWithComment(FakeCoreApi):
    def fetch_comments(self, post_id: str) -> list[Any]:
        from app.clients.core_api import CoreComment

        when = "2026-11-10T00:00:00Z"
        return [
            CoreComment.model_validate(
                {
                    "id": "c1",
                    "authorId": "u1",
                    "body": "Phòng sạch",
                    "createdAt": when,
                    "updatedAt": when,
                }
            )
        ]


@pytest.mark.parametrize("store_error", [None, RuntimeError("redis down")])
def test_stored_labels_feed_the_run_and_a_broken_store_only_costs_time(
    monkeypatch: pytest.MonkeyPatch, store_error: Exception | None
) -> None:
    seen: list[Any] = []

    def fake_run(**kwargs: Any) -> SummaryRun:
        seen.append(kwargs["known_labels"])
        kwargs["keep_labels"]({"c1": _LABEL})  # the pipeline keeps them before the LLM call
        return SummaryRun(None, new_labels={"c1": _LABEL})

    monkeypatch.setattr(summary_worker, "run_summary", fake_run)
    store = _Store(store_error)
    worker = SummaryWorker(
        cast(Any, FakeRedis()),
        cast(CoreApiClient, _CoreWithComment()),
        FakeLlmClient(),
        classifier=_Classifier(),
        label_store=store,
        consumer_name="test",
        clock_ms=lambda: 1_000,
    )

    worker.summarize_post(POST)

    assert seen == [{} if store_error else {"c1": _LABEL}]
    assert store.kept == ["c1"]  # only reading failed: new labels are still kept


class _CoreWithSample(FakeCoreApi):
    def __init__(self, held: list[str] | None = None, held_error: Exception | None = None) -> None:
        super().__init__()
        self.held = held or []
        self.held_error = held_error
        self.sample_calls: list[tuple[int, str]] = []
        self.held_calls = 0

    def fetch_comment_sample(self, post_id: str, size: int, seed: str) -> Any:
        from app.clients.core_api import CoreCommentSample

        self.sample_calls.append((size, seed))
        item = {
            "id": "c1",
            "authorId": "u1",
            "body": "Phòng sạch",
            "createdAt": "2026-11-10T00:00:00Z",
        }
        stats = {"visibleCommentCount": 9_000, "uniqueAuthorCount": 4_000}
        return CoreCommentSample.model_validate({"stats": stats, "items": [item]})

    def iter_held_summaries(self) -> list[str]:
        self.held_calls += 1
        if self.held_error:
            raise self.held_error
        return self.held


def test_a_run_reads_cores_sample_with_its_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []

    def fake_run(**kwargs: Any) -> SummaryRun:
        seen.append(kwargs)
        return SummaryRun(None)

    monkeypatch.setattr(summary_worker, "run_summary", fake_run)
    core = _CoreWithSample()

    _worker(FakeRedis(), core).summarize_post(POST)

    assert core.sample_calls == [(summary_worker.SAMPLE_SIZE, POST)]  # same seed every run
    [kwargs] = seen
    assert [c.comment_id for c in kwargs["comments"]] == ["c1"]
    assert (kwargs["post_stats"].comments, kwargs["post_stats"].writers) == (9_000, 4_000)


def test_an_older_core_falls_back_to_the_newest_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(
        summary_worker, "run_summary", lambda **kw: seen.append(kw) or SummaryRun(None)
    )

    _worker(FakeRedis(), cast(Any, _CoreWithComment())).summarize_post(POST)

    assert [c.comment_id for c in seen[0]["comments"]] == ["c1"]
    assert seen[0]["post_stats"] is None  # no whole-post counts: exact counts only


def test_reconciliation_runs_on_one_replica_and_schedules_held_posts_like_backfill() -> None:
    redis = FakeRedis()
    core = _CoreWithSample(held=[POST, "p-2"])
    first, second = _worker(redis, core), _worker(redis, core)

    assert first.maybe_reconcile() == 2
    assert second.maybe_reconcile() == 0  # the key is taken for 6 h
    assert core.held_calls == 1
    assert {POST, "p-2"} <= set(redis.zset)


def test_a_failed_reconciliation_is_tried_again_soon() -> None:
    redis = FakeRedis()
    core = _CoreWithSample(held_error=httpx.ConnectError("core down"))

    with pytest.raises(httpx.ConnectError):
        _worker(redis, core).maybe_reconcile()

    assert redis.kv[summary_worker.RECONCILE_KEY] == "1000"
    assert redis.ttl[summary_worker.RECONCILE_KEY] == summary_worker.RECONCILE_RETRY_MS


def test_an_older_core_without_reconciliation_only_waits() -> None:
    response = httpx.Response(404, request=httpx.Request("GET", "http://core"))
    error = httpx.HTTPStatusError("404", request=response.request, response=response)
    redis = FakeRedis()

    assert _worker(redis, _CoreWithSample(held_error=error)).maybe_reconcile() == 0
    assert summary_worker.RECONCILE_KEY in redis.kv
