import asyncio
import json
import os
from typing import cast
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
import redis
from pydantic import ValidationError

from app.services import usage_events
from app.services.usage_events import (
    USAGE_STREAM,
    ChatTurn,
    ChatTurnEvent,
    ChatUsage,
    UsageEvent,
    close_usage_redis,
    publish_usage,
    publish_worker_usage,
)
from scripts.export_usage_events import CHAT_TURN_CONTRACT, CONTRACT


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


def _chat_turn() -> ChatTurnEvent:
    return ChatTurnEvent(
        user_id=uuid4(),
        payload=ChatTurn(
            conversation_id=uuid4(),
            question="private question",
            intent=None,
            answer_kind="answer",
            is_action=False,
        ),
    )


def test_checked_in_contract_matches_chat_turn_events() -> None:
    expected = ChatTurnEvent.model_json_schema(mode="serialization", by_alias=True)
    expected["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    assert json.loads(CHAT_TURN_CONTRACT.read_text(encoding="utf-8")) == expected
    assert "userId" in expected["required"]
    assert expected["$defs"]["ChatTurn"]["properties"]["question"]["maxLength"] == 120


@pytest.mark.parametrize("event", [_chat_usage(), _chat_turn()])
def test_old_events_without_turn_metadata_still_validate(event) -> None:
    data = event.model_dump(mode="json", by_alias=True)
    data["payload"].pop("turnId")
    data["payload"].pop("latencyMs")
    restored = type(event).model_validate(data)
    assert isinstance(restored.payload, (ChatUsage, ChatTurn))
    assert restored.payload.turn_id is None and restored.payload.latency_ms is None


@pytest.mark.parametrize("event", [_chat_usage(), _chat_turn()])
def test_latency_must_be_nonnegative_and_uses_camel_case(event) -> None:
    turn_id = uuid4()
    data = event.model_dump(mode="json", by_alias=True)
    data["payload"].update(turnId=str(turn_id), latencyMs=123)
    restored = type(event).model_validate(data)
    assert isinstance(restored.payload, (ChatUsage, ChatTurn))
    assert restored.payload.turn_id == turn_id and restored.payload.latency_ms == 123
    assert restored.model_dump(mode="json", by_alias=True)["payload"]["turnId"] == str(turn_id)
    data["payload"]["latencyMs"] = -1
    with pytest.raises(ValidationError):
        type(event).model_validate(data)


@pytest.mark.parametrize("user", [{}, {"userId": None}])
def test_chat_turn_requires_a_user(user) -> None:
    data = _chat_turn().model_dump(mode="json", by_alias=True)
    del data["userId"]
    with pytest.raises(ValidationError):
        ChatTurnEvent.model_validate(data | user)


def test_redis_outage_does_not_log_chat_turn_question(monkeypatch, caplog) -> None:
    monkeypatch.setattr(usage_events, "get_usage_redis", Mock(side_effect=redis.ConnectionError))
    usage, turn = _chat_usage(), _chat_turn()
    asyncio.run(publish_usage([usage, turn]))
    assert caplog.records[0].usageEvent == usage.model_dump(mode="json", by_alias=True)
    record = caplog.records[1]
    assert record.getMessage() == "ai.chat_turn.publish_failed"
    assert record.eventId == str(turn.event_id)
    assert "usageEvent" not in record.__dict__
    assert turn.payload.question not in repr([r.__dict__ for r in caplog.records])


def test_usage_and_chat_turn_share_one_stream_pipeline(monkeypatch) -> None:
    pipe = AsyncMock()
    pipe.xadd = Mock()
    pipe.__aenter__.return_value = pipe
    client = Mock()
    client.pipeline.return_value = pipe
    monkeypatch.setattr(usage_events, "get_usage_redis", lambda: client)
    events = [_chat_usage(), _chat_turn()]
    asyncio.run(publish_usage(events))
    client.pipeline.assert_called_once_with(transaction=False)
    pipe.execute.assert_awaited_once()
    assert pipe.xadd.call_count == 2
    for call, event in zip(pipe.xadd.call_args_list, events, strict=True):
        assert call.args == (USAGE_STREAM, {"event": event.model_dump_json(by_alias=True)})


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
