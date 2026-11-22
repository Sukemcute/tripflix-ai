"""Backfill: schedule a summary run for posts that never got a comment event.

The worker only wakes on comment events, so posts whose comments came in without one get
no summary: seed data (core's seed script inserts rows, no outbox event), comments from
before the worker was deployed, or events trimmed from the stream while the worker was down
(core trims `stream:core.content` to ~100k entries, acknowledged or not). Run it after the
first deploy, after a prompt, lexicon or model change, and after an outage:

    uv run python -m app.workers.backfill --dry-run
    uv run python -m app.workers.backfill

It only schedules; the running worker does the summaries through the normal path (rules,
5-person gate, input hash, LLM, validator, PUT), so users keep reading the old summary until
a new one is saved. Safe to run again (BAO_CAO "Backfill"):
- ZADD NX never moves a run that is already scheduled (a live event's run stays first);
- a post whose input did not change hits the same input hash and costs no LLM call;
- runs are spread `spacing` apart so live events (due in 60 s) are not stuck behind it.
"""

import argparse
import logging
from dataclasses import dataclass

import redis

from app.clients.core_api import CoreApiClient
from app.core.config import get_settings
from app.services.summary.selection import MIN_PEOPLE
from app.workers.summary_worker import SummaryScheduler, read_clock_ms

logger = logging.getLogger(__name__)

DEFAULT_SPACING_SECONDS = 2.0  # [HIỆU CHỈNH] one LLM run took ~3-9 s in a real trial


@dataclass(frozen=True)
class BackfillReport:
    scanned: int
    eligible: int
    scheduled: int
    already_scheduled: int


def run_backfill(
    core: CoreApiClient,
    scheduler: SummaryScheduler | None,
    *,
    start_ms: int,
    spacing_ms: int,
    min_comments: int = MIN_PEOPLE,
) -> BackfillReport:
    """Schedule every public post with enough comments; scheduler None means dry run.

    min_comments is a cheap pre-filter on core's comment count: fewer comments than the
    5-person gate can never be summarized. The worker still applies the real gate.
    """
    scanned = eligible = scheduled = already = 0
    for post in core.iter_public_posts():
        scanned += 1
        if post.comment_count < min_comments:
            continue
        due = start_ms + eligible * spacing_ms
        eligible += 1
        if scheduler is None:
            continue
        if scheduler.schedule_backfill(post.id, due):
            scheduled += 1
        else:
            already += 1
    return BackfillReport(scanned, eligible, scheduled, already)


def main() -> None:
    parser = argparse.ArgumentParser(description="Schedule summary runs for existing posts.")
    parser.add_argument("--dry-run", action="store_true", help="count posts, write nothing")
    parser.add_argument("--spacing-seconds", type=float, default=DEFAULT_SPACING_SECONDS)
    args = parser.parse_args()

    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    core = CoreApiClient(
        settings.core_api_url, settings.service_client_id, settings.service_client_secret
    )
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    scheduler = None if args.dry_run else SummaryScheduler(client)
    report = run_backfill(
        core,
        scheduler,
        start_ms=read_clock_ms(),
        spacing_ms=int(args.spacing_seconds * 1000),
    )
    logger.info(
        "backfill%s: %d posts scanned, %d with %d+ comments, %d scheduled, %d already scheduled",
        " (dry run)" if args.dry_run else "",
        report.scanned,
        report.eligible,
        MIN_PEOPLE,
        report.scheduled,
        report.already_scheduled,
    )


if __name__ == "__main__":
    main()
