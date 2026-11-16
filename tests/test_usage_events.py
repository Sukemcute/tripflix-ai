import asyncio
import json
import os
from typing import cast
from unittest.mock import Mock
from uuid import uuid4

import pytest
import redis

from app.services import usage_events
from app.services.usage_events import (
    USAGE_STREAM,
    ChatUsage,
    UsageEvent,
    close_usage_redis,
    publish_usage,
    publish_worker_usage,
)
from scripts.export_usage_events import CONTRACT


def _chat_usage() -> UsageEvent:
    return UsageEvent(
        user_id=uuid4(),
        payload=ChatUsage(
            conversation_id=uuid4(),
            step="responder",
            model="test-model",
            input_tokens=80,
            output_tokens=20,
            cost_usd=0.001,
        ),
    )


def test_checked_in_contract_matches_usage_events() -> None:
    expected = UsageEvent.model_json_schema(mode="serialization", by_alias=True)
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    assert json.loads(CONTRACT.read_text(encoding="utf-8")) == expected
    assert {"eventId", "type", "occurredAt", "payload"} <= set(expected["required"])


def test_redis_outage_leaves_the_original_event_in_the_log(monkeypatch, caplog) -> None:
    blocked = Mock(side_effect=redis.ConnectionError)
    monkeypatch.setattr(usage_events, "get_usage_redis", blocked)
    sync_client = Mock(spec=redis.Redis)
    sync_client.xadd.side_effect = redis.ConnectionError
    event = _chat_usage()

    asyncio.run(publish_usage([event]))
    publish_worker_usage(sync_client, event)

    expected = event.model_dump(mode="json", by_alias=True)
    assert [record.__dict__["usageEvent"] for record in caplog.records] == [expected, expected]


@pytest.mark.skipif(not os.environ.get("REDIS_TEST_URL"), reason="REDIS_TEST_URL not set")
def test_redis_stream_preserves_the_event_id_when_the_same_event_is_republished(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.environ["REDIS_TEST_URL"]
    monkeypatch.setenv("REDIS_URL", url)
    event = _chat_usage()
    other_call = _chat_usage()

    async def send() -> None:
        try:
            await publish_usage([event, other_call])
        finally:
            await close_usage_redis()

    asyncio.run(send())
    with usage_events.create_worker_usage_redis(url) as client:
        publish_worker_usage(client, event)
    with redis.Redis.from_url(url, decode_responses=True) as client:
        entries = cast(list[tuple[str, dict[str, str]]], client.xrevrange(USAGE_STREAM, count=3))
    received = [UsageEvent.model_validate_json(fields["event"]) for _, fields in entries]
    assert received == [event, other_call, event]
    assert received[0].event_id != received[1].event_id
