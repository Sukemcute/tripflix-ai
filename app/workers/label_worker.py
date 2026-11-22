"""Label worker: label each comment once, when it is written, for every later summary run.

Run: `uv run python -m app.workers.label_worker`. Its own consumer group (`ai-labels`) on the
same stream as the summary worker, its own process, so labelling scales out without slowing
summaries down (bulkhead).

- created / updated: a root comment is labelled from the event body. Replies wait for the
  summary run, which has the parent text the classifier was trained with.
- cascade: a comment the single-comment rules drop (spam, link, too short, video reaction)
  needs no label and skips the model, unless the safety rules flag it.
- safety: every written comment, reply or root, that the safety rules flag keeps its result
  (categories, public or held for review), so a warning outside core's sample still reaches
  the summary. Never the comment text. Own visit or hearsay is the model's call for replies
  too, as in a summary run; their labels are not stored (made without the parent text).
- updated: the old label and safety result go first, the new text decides again.
- deleted / hidden: its label and safety result are removed.
- restored: a write, but core's event has no body yet, so today the next summary run labels it.
- the classifier fails or its breaker is open: the batch is acked without labels. Summary
  runs still label what they need, as before, so nothing is lost but time.
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

from app.core.config import get_settings
from app.services.summary.comment_classifier import CommentClassifier, CommentLabels
from app.services.summary.filters import filter_comments
from app.services.summary.label_store import (
    LabelStore,
    RedisLabelStore,
    StoredLabel,
    StoredSafety,
    content_hash,
)
from app.services.summary.safety import match_safety
from app.services.summary.schemas import CommentIn
from app.workers.summary_worker import (
    BATCH_SIZE,
    BLOCK_MS,
    CLAIM_IDLE_MS,
    DEAD_LETTER_STREAM,
    STREAM,
    _Envelope,  # pyright: ignore[reportPrivateUsage]
    build_classifier,
)

logger = logging.getLogger(__name__)

GROUP = "ai-labels"
# restored carries no body today (contracts/events): handled as a write so it labels the
# comment as soon as core adds the body; until then it is a no-op and summary runs label it.
WRITE_EVENTS = {"content.comment.created", "content.comment.updated", "content.comment.restored"}
GONE_EVENTS = {"content.comment.deleted", "content.comment.hidden"}


class _Payload(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")
    comment_id: str
    post_id: str
    author_id: str = ""
    body: str = ""
    parent_comment_id: str | None = None
    post_author_id: str | None = None


class LabelWorker:
    def __init__(
        self,
        client: Any,
        store: LabelStore,
        classifier: CommentClassifier | None,
        *,
        consumer_name: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.redis = client
        self.store = store
        self.classifier = classifier
        self.consumer = consumer_name or f"{socket.gethostname()}-{os.getpid()}-labels"
        self.clock = clock

    def handle_batch(self, entries: list[tuple[str, dict[str, str]]]) -> None:
        writes: list[_Payload] = []
        for message_id, fields in entries:
            raw = fields.get("event", "")
            try:
                event = _Envelope.model_validate_json(raw)
                payload = _Payload.model_validate(event.payload)
            except ValidationError as e:
                self.redis.xadd(
                    DEAD_LETTER_STREAM,
                    {
                        "event": raw,
                        "stream": STREAM,
                        "group": GROUP,
                        "messageId": message_id,
                        "reason": f"unreadable event: {e.error_count()} errors",
                    },
                )
                continue
            if event.type in GONE_EVENTS or event.type == "content.comment.updated":
                self.store.remove(payload.post_id, payload.comment_id)
            if event.type in WRITE_EVENTS:
                writes.append(payload)
        labels = self._label([p for p in writes if self._needs_label(p)])
        # A reply's own visit decides its warning too, so it is read by the model like a summary
        # run would (there with its parent; the parent text is unknown here). Not stored: the
        # summary run labels replies with their parent.
        replies = [p for p in writes if p.parent_comment_id and p.body.strip()]
        labels |= self._label([p for p in replies if match_safety(p.body)], keep=False)
        for p in writes:
            label = labels.get(p.comment_id)
            if hit := match_safety(p.body, label.is_first_hand if label else None):
                self.store.put_safety(
                    p.post_id, StoredSafety(p.comment_id, hit.categories, hit.visibility)
                )
        for message_id, _ in entries:
            self.redis.xack(STREAM, GROUP, message_id)

    def _needs_label(self, p: _Payload) -> bool:
        if p.parent_comment_id is not None or not p.body.strip():
            return False  # replies: the summary run has their parent text
        if match_safety(p.body):
            return True  # first-hand decides public warning or moderator queue
        comment = CommentIn(
            comment_id=p.comment_id,
            author_id=p.author_id or p.comment_id,
            body=p.body,
            status="visible",
            created_at=self.clock(),
            is_post_author=bool(p.post_author_id) and p.author_id == p.post_author_id,
        )
        return bool(filter_comments([comment], self.clock()).candidates)

    def _label(self, items: list[_Payload], *, keep: bool = True) -> dict[str, CommentLabels]:
        if not items or self.classifier is None:
            return {}
        try:
            found = self.classifier.classify([(p.body, "") for p in items])
        except Exception:
            logger.exception(
                "labelling %s comments failed, summary runs will label them", len(items)
            )
            return {}
        for p, labels in zip(items, found, strict=True) if keep else ():
            stored = StoredLabel(labels, self.classifier.version, content_hash(p.body))
            self.store.put(p.post_id, p.comment_id, p.author_id or p.comment_id, stored)
        return {p.comment_id: labels for p, labels in zip(items, found, strict=True)}

    def ensure_group(self) -> None:
        try:
            self.redis.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def poll_once(self) -> None:
        stale = cast(
            list[Any],
            self.redis.xautoclaim(STREAM, GROUP, self.consumer, CLAIM_IDLE_MS, "0-0", BATCH_SIZE),
        )
        self.handle_batch([(i, f) for i, f in stale[1] if f])
        fresh = cast(
            list[Any] | None,
            self.redis.xreadgroup(GROUP, self.consumer, {STREAM: ">"}, BATCH_SIZE, BLOCK_MS),
        )
        self.handle_batch([e for _, entries in fresh or [] for e in entries])

    def run_forever(self) -> None:
        self.ensure_group()
        logger.info("label worker %s listening on %s", self.consumer, STREAM)
        while True:
            try:
                self.poll_once()
            except redis.ConnectionError:
                logger.exception("redis unavailable, retrying")
                self.redis.connection_pool.disconnect()


def main() -> None:
    settings = get_settings()
    logging.basicConfig(level=settings.log_level)
    client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    classifier = build_classifier(settings)
    if classifier is None:
        logger.warning("no classifier: only removals are applied, summary runs label as before")
    LabelWorker(
        client,
        RedisLabelStore(client),
        classifier,
        consumer_name=settings.label_worker_consumer_name or None,
    ).run_forever()


if __name__ == "__main__":
    main()
