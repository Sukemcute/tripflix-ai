"""Usage events sent by ai-service and the summary worker (TF95)."""

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from functools import cache
from typing import Literal
from uuid import UUID, uuid4

import redis
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from pydantic_settings import BaseSettings, SettingsConfigDict
from redis import asyncio as aioredis
from redis.asyncio.retry import Retry as AsyncRetry
from redis.backoff import NoBackoff
from redis.retry import Retry
from redis.typing import EncodableT, FieldT

logger = logging.getLogger(__name__)
USAGE_STREAM = "stream:ai"
STREAM_MAXLEN = 100_000
PUBLISH_SECONDS = 0.25


class _WireModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="forbid",
        json_schema_serialization_defaults_required=True,
    )


class _LlmUsage(_WireModel):
    model: str
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    estimated: Literal[True] = True


class ChatUsage(_LlmUsage):
    feature: Literal["chat"] = "chat"
    conversation_id: UUID
    step: Literal["controller", "responder"]
    turn_id: UUID | None = None
    latency_ms: int | None = Field(default=None, ge=0)


class SummaryUsage(_LlmUsage):
    feature: Literal["summary"] = "summary"
    estimated_comment_tokens: int = Field(ge=0)


class ModerationUsage(_WireModel):
    feature: Literal["moderation"] = "moderation"
    model: str
    # The moderation provider exposes neither token count and charges zero for the batch.
    input_tokens: None = None
    output_tokens: None = None
    cost_usd: Literal[0] = 0
    estimated: Literal[False] = False
    items: int = Field(ge=1)
    images: int = Field(ge=0)


class CoverOcrUsage(_WireModel):
    feature: Literal["cover_ocr"] = "cover_ocr"
    model: str
    step: Literal["completed", "error", "usage_missing"]
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float = Field(ge=0, allow_inf_nan=False)
    estimated: Literal[True] = True


class UsageEvent(_WireModel):
    event_id: UUID = Field(default_factory=uuid4)
    type: Literal["ai.usage.recorded"] = "ai.usage.recorded"
    version: Literal[1] = 1
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    producer: Literal["ai-service"] = "ai-service"
    user_id: UUID | None = None
    payload: ChatUsage | SummaryUsage | ModerationUsage | CoverOcrUsage


class ChatTurn(_WireModel):
    conversation_id: UUID
    question: str = Field(max_length=120)
    intent: str | None
    answer_kind: str
    is_action: bool
    turn_id: UUID | None = None
    latency_ms: int | None = Field(default=None, ge=0)


class ChatTurnEvent(_WireModel):
    event_id: UUID = Field(default_factory=uuid4)
    type: Literal["ai.chat.turn.recorded"] = "ai.chat.turn.recorded"
    version: Literal[1] = 1
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(UTC))
    producer: Literal["ai-service"] = "ai-service"
    user_id: UUID
    payload: ChatTurn


class _UsageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", env_ignore_empty=True)
    redis_url: str = "redis://localhost:6379/0"


@cache
def get_usage_redis() -> aioredis.Redis:
    return aioredis.Redis.from_url(_UsageSettings().redis_url, retry=AsyncRetry(NoBackoff(), 0))


async def close_usage_redis() -> None:
    if get_usage_redis.cache_info().currsize:
        await get_usage_redis().aclose()
        get_usage_redis.cache_clear()


def create_worker_usage_redis(url: str) -> redis.Redis:
    # The worker's usual Redis pool also blocks reading its input stream.
    return redis.Redis.from_url(
        url,
        socket_connect_timeout=PUBLISH_SECONDS,
        socket_timeout=PUBLISH_SECONDS,
        retry=Retry(NoBackoff(), 0),
    )


def _fields(event: UsageEvent | ChatTurnEvent) -> dict[FieldT, EncodableT]:
    return {"event": event.model_dump_json(by_alias=True)}


def _log_unpublished(event: UsageEvent | ChatTurnEvent) -> None:
    if isinstance(event, ChatTurnEvent):
        logger.warning("ai.chat_turn.publish_failed", extra={"eventId": str(event.event_id)})
        return
    logger.warning(
        "ai.usage.publish_failed",
        extra={"usageEvent": event.model_dump(mode="json", by_alias=True)},
    )


async def publish_usage(events: Sequence[UsageEvent | ChatTurnEvent]) -> None:
    if not events:
        return
    try:
        async with asyncio.timeout(PUBLISH_SECONDS):
            async with get_usage_redis().pipeline(transaction=False) as pipe:
                for event in events:
                    pipe.xadd(USAGE_STREAM, _fields(event), maxlen=STREAM_MAXLEN)
                await pipe.execute()
    except (redis.RedisError, OSError, ValueError):
        for event in events:
            _log_unpublished(event)


def publish_worker_usage(client: redis.Redis, event: UsageEvent) -> None:
    try:
        client.xadd(USAGE_STREAM, _fields(event), maxlen=STREAM_MAXLEN)
    except (redis.RedisError, OSError, ValueError):
        _log_unpublished(event)
