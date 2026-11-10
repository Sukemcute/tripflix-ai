"""Authenticated TF31 SSE entry point, with bounded calls and fail-closed session checks."""

import asyncio
import json
import logging
import re
from functools import cache
from pathlib import Path
from typing import Annotated

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from starlette.concurrency import run_in_threadpool

from app.services.assistant import (
    Answer,
    ChatRequest,
    Understanding,
    build_understanding_input,
    search,
    search_flights,
    search_stays,
)
from app.services.summary.pii import mask_pii

router = APIRouter()
bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


class ChatSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    core_api_url: str = "http://localhost:3000"
    jwks_url: str = ""
    auth_jwt_issuer: str = "tripflix-core"
    auth_jwt_audience: str = "tripflix"
    chat_llm_enabled: bool = False
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    chat_model: str = "deepseek-flash"
    chat_timeout_seconds: float = Field(default=12, gt=0, le=60)
    # Set from the provider price sheet for the selected model before live evaluation.
    chat_input_usd_per_million: float = Field(default=0.3, ge=0)
    chat_cached_usd_per_million: float = Field(default=0.006, ge=0)
    chat_output_usd_per_million: float = Field(default=1.2, ge=0)


@cache
def get_chat_settings() -> ChatSettings:
    return ChatSettings()


@cache
def get_jwks(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, timeout=3)


def verify_user_token(token: str, settings: ChatSettings) -> str:
    url = settings.jwks_url or f"{settings.core_api_url.rstrip('/')}/.well-known/jwks.json"
    claims = jwt.decode(
        token,
        get_jwks(url).get_signing_key_from_jwt(token).key,
        algorithms=["ES256"],
        issuer=settings.auth_jwt_issuer,
        audience=settings.auth_jwt_audience,
        options={"require": ["sub", "sid", "role", "iat", "exp"]},
    )
    if (
        claims.get("typ") == "service"
        or claims["role"] not in {"member", "moderator", "superadmin"}
        or not isinstance(claims["sid"], str)
        or not claims["sid"]
        or not claims["sub"]
    ):
        raise jwt.InvalidTokenError("invalid user claims")
    return str(claims["sub"])


async def require_chat_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[ChatSettings, Depends(get_chat_settings)],
) -> str:
    if credentials is None:
        raise HTTPException(
            401, "Bạn cần đăng nhập để dùng trợ lý.", headers={"WWW-Authenticate": "Bearer"}
        )
    try:
        user_id = await run_in_threadpool(verify_user_token, credentials.credentials, settings)
        # Core owns revocation/account locks. Do not retain or send its profile to the LLM.
        async with httpx.AsyncClient(base_url=settings.core_api_url, timeout=3) as core:
            response = await core.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {credentials.credentials}"}
            )
        if response.status_code in {401, 403}:
            raise HTTPException(401, "Phiên đăng nhập không còn hiệu lực.")
        response.raise_for_status()
        return user_id
    except jwt.PyJWKClientConnectionError as exc:
        raise HTTPException(503, "Chưa thể kiểm tra phiên đăng nhập.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(
            401, "Token không hợp lệ.", headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(503, "Chưa thể kiểm tra phiên đăng nhập.") from exc


def event(name: str, payload: dict) -> str:
    return f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def understand(request: ChatRequest, settings: ChatSettings, usage: dict) -> Understanding:
    prompt = (Path(__file__).parents[1] / "prompts" / "assistant-understand.v2.md").read_text(
        encoding="utf-8"
    )
    async with httpx.AsyncClient(base_url=settings.deepseek_base_url, timeout=5) as llm:
        response = await llm.post(
            "/chat/completions",
            headers={"Authorization": f"Bearer {settings.deepseek_api_key.get_secret_value()}"},
            json={
                "model": settings.chat_model,
                "thinking": {"type": "disabled"},
                "temperature": 0,
                "max_tokens": 350,
                "response_format": {"type": "json_object"},
                "messages": [
                    {
                        "role": "system",
                        "content": prompt + json.dumps(Understanding.model_json_schema()),
                    },
                    {"role": "user", "content": build_understanding_input(request)},
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        billed = payload.get("usage", {})
        incoming = max(0, int(billed.get("prompt_tokens", 0)))
        cached = min(incoming, max(0, int(billed.get("prompt_cache_hit_tokens", 0))))
        outgoing = max(0, int(billed.get("completion_tokens", 0)))
        usage.update(
            inputTokens=incoming,
            outputTokens=outgoing,
            costUsd=(
                (incoming - cached) * settings.chat_input_usd_per_million
                + cached * settings.chat_cached_usd_per_million
                + outgoing * settings.chat_output_usd_per_million
            )
            / 1_000_000,
            estimated=True,
        )
        logger.info(
            "ai.usage.recorded",
            extra={
                "feature": "chat",
                "conversation_id": str(request.conversation_id),
                "step": "understand",
                "model": settings.chat_model,
                "usage": usage.copy(),
            },
        )
        return Understanding.model_validate_json(payload["choices"][0]["message"]["content"])


@router.post(
    "/chat",
    tags=["assistant"],
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def chat(
    request: ChatRequest,
    user: Annotated[str, Depends(require_chat_user)],
    settings: Annotated[ChatSettings, Depends(get_chat_settings)],
):
    async def stream():
        usage = {"inputTokens": 0, "outputTokens": 0, "costUsd": 0.0, "estimated": True}
        yield event("status", {"step": "understanding"})
        try:
            async with asyncio.timeout(settings.chat_timeout_seconds):
                parsed = None
                llm_status = "disabled"
                if settings.chat_llm_enabled and settings.deepseek_api_key.get_secret_value():
                    yield event("status", {"step": "llm", "outcome": "calling"})
                    try:
                        parsed = await understand(request, settings, usage)
                        llm_status = "ok"
                    except httpx.HTTPStatusError as exc:
                        llm_status = f"http_{exc.response.status_code}"
                    except httpx.HTTPError:
                        llm_status = "connection_error"
                    except (ValueError, KeyError, IndexError, TypeError):
                        llm_status = "invalid_response"
                elif settings.chat_llm_enabled:
                    llm_status = "missing_key"
                yield event("status", {"step": "llm", "outcome": llm_status})
                if parsed and (
                    parsed.intent == "refusal"
                    or (request.search_mode is None and parsed.intent in {"small_talk", "clarify"})
                ):
                    if parsed.intent == "refusal":
                        answer = Answer(
                            kind="refusal",
                            text="Mình hỗ trợ du lịch an toàn. Bạn muốn khám phá nơi nào?",
                        )
                    elif parsed.intent == "small_talk":
                        answer = Answer(
                            kind="answer",
                            text="Mình là Tripi, trợ lý du lịch của Tripflix. "
                            "Mình có thể giúp bạn tìm Reel, lộ trình, khách sạn và chuyến bay.",
                        )
                    else:
                        place = parsed.place.strip()
                        if parsed.missing == "dates":
                            destination = f" {place}" if place else ""
                            question = f"Bạn dự định đi{destination} vào ngày nào?"
                        elif place:
                            question = f"Bạn muốn tìm lộ trình, chỗ ở hay chuyến bay đến {place}?"
                        elif parsed.missing == "place":
                            question = "Bạn muốn đi đâu?"
                        else:
                            question = "Bạn muốn mình tìm gì cho chuyến đi này?"
                        answer = Answer(kind="clarify", text=question)
                else:
                    yield event("status", {"step": "searching"})
                    query = parsed.query if parsed else mask_pii(request.message)
                    async with httpx.AsyncClient(base_url=settings.core_api_url, timeout=3) as core:
                        if request.search_mode == "reel":
                            answer = await search(
                                core,
                                mask_pii(request.message.strip()),
                                reels_only=True,
                                fallback=parsed is None,
                            )
                        elif parsed and parsed.intent == "find_stay":
                            answer = await search_stays(core, parsed)
                        elif parsed and parsed.intent == "find_flight":
                            if re.search(
                                r"\b(?:rẻ nhất|re nhat|cheapest)\b", request.message, re.I
                            ):
                                parsed.cheapest_only = True
                            answer = await search_flights(core, parsed)
                        else:
                            reel_request = re.match(
                                r"^(?:(?:tìm|tim|cho mình xem)\s+)?(?:reels?|video)\b\s*",
                                request.message.strip(),
                                re.IGNORECASE,
                            )
                            if reel_request and parsed is None:
                                query = mask_pii(request.message.strip()[reel_request.end() :])
                            answer = await search(
                                core,
                                query,
                                fallback=parsed is None,
                                reels_only=bool(
                                    reel_request or (parsed and parsed.intent == "find_reel")
                                ),
                            )
                yield event("text", {"delta": answer.text})
                yield event(
                    "cards",
                    {
                        "items": [
                            card.model_dump(mode="json", by_alias=True) for card in answer.cards
                        ]
                    },
                )
                yield event("done", {"kind": answer.kind, "usage": usage})
        except (TimeoutError, httpx.HTTPError, ValidationError, ValueError):
            yield event("error", {"code": "DEPENDENCY_UNAVAILABLE", "usage": usage})

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
