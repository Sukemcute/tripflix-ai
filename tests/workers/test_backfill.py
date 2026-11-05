from typing import Any, cast

from app.clients.core_api import CoreApiClient, CorePostListItem
from app.workers.backfill import run_backfill
from app.workers.summary_worker import DUE_KEY, MIN_GAP_MS, SummaryScheduler


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.zset: dict[str, float] = {}

    def get(self, key: str) -> str | None:
        return self.kv.get(key)

    def zadd(self, key: str, mapping: dict[str, float], nx: bool = False) -> int:
        added = 0
        for member, score in mapping.items():
            if nx and member in self.zset:
                continue
            added += member not in self.zset
            self.zset[member] = score
        return added


class FakeCore:
    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts

    def iter_public_posts(self) -> list[CorePostListItem]:
        return [CorePostListItem(id=i, comment_count=n) for i, n in self.counts.items()]


def _run(redis: FakeRedis | None, counts: dict[str, int]):  # noqa: ANN202
    scheduler = SummaryScheduler(cast(Any, redis)) if redis else None
    return run_backfill(
        cast(CoreApiClient, FakeCore(counts)), scheduler, start_ms=1_000, spacing_ms=2_000
    )


def test_posts_with_enough_comments_are_spread_out() -> None:
    redis = FakeRedis()

    report = _run(redis, {"p1": 6, "p2": 2, "p3": 40})

    assert redis.zset == {"p1": 1_000, "p3": 3_000}  # p2 cannot reach 5 people
    assert (report.scanned, report.eligible, report.scheduled) == (3, 2, 2)


def test_dry_run_writes_nothing() -> None:
    report = _run(None, {"p1": 6, "p3": 40})

    assert (report.eligible, report.scheduled) == (2, 0)


def test_a_run_already_scheduled_by_a_live_event_is_kept() -> None:
    redis = FakeRedis()
    redis.zset["p1"] = 500  # live comment event: due sooner

    report = _run(redis, {"p1": 6})

    assert redis.zset["p1"] == 500
    assert report.already_scheduled == 1


def test_a_post_that_just_ran_waits_for_the_gap() -> None:
    redis = FakeRedis()
    redis.kv["ai:summary:last_run:p1"] = "900"
    assert DUE_KEY == "ai:summary:due"

    _run(redis, {"p1": 6})

    assert redis.zset["p1"] == 900 + MIN_GAP_MS
