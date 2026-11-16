"""POST /chat for Tripi on the mobile reel app (TF31): SSE, bounded calls, budgets per user.

Guests may chat on a small budget (Bảo, 2026-11-16); a bad or expired token is still a 401 so
the app refreshes it instead of silently dropping to the guest budget.
"""

import asyncio
import json
import logging
import re
from functools import cache
from typing import Annotated

import anyio
import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import ValidationError
from redis import asyncio as aioredis
from starlette.concurrency import run_in_threadpool

from app.clients.llm.base import LlmResult
from app.clients.llm.guarded import LlmUnavailableError
from app.core.config import ChatSettings, get_chat_settings
from app.services.assistant import (
    Answer,
    ChatRequest,
    search,
    search_flights,
    search_stays,
)
from app.services.assistant.admission import (
    ChatRejectedError,
    Identity,
    RedisCounters,
    Ticket,
    TurnGate,
    guest_identity,
    user_identity,
)
from app.services.assistant.understand import LlmNotConfiguredError, understand
from app.services.summary.pii import mask_pii

__all__ = ["ChatSettings", "get_chat_settings", "router"]

router = APIRouter()
bearer = HTTPBearer(auto_error=False)
logger = logging.getLogger(__name__)


@cache
def get_jwks(url: str) -> jwt.PyJWKClient:
    return jwt.PyJWKClient(url, timeout=3)


@cache
def get_core_client() -> httpx.AsyncClient:
    """One pool to Core per process: no TCP and TLS handshake per call."""
    settings = get_chat_settings()
    return httpx.AsyncClient(
        base_url=settings.core_api_url,
        timeout=3,
        limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
    )


@cache
def get_gate() -> TurnGate:
    settings = get_chat_settings()
    store = aioredis.Redis.from_url(settings.redis_url, decode_responses=True)
    return TurnGate(settings, RedisCounters(store))


def verify_user_token(token: str, settings: ChatSettings) -> str:
    claims = jwt.decode(
        token,
        get_jwks(settings.resolved_jwks_url).get_signing_key_from_jwt(token).key,
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


async def resolve_identity(
    http_request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    settings: ChatSettings,
) -> Identity:
    if credentials is None:
        if settings.chat_require_login:
            raise HTTPException(
                401, "Bạn cần đăng nhập để dùng trợ lý.", headers={"WWW-Authenticate": "Bearer"}
            )
        # Behind the gateway this is the forwarded client IP (uvicorn FORWARDED_ALLOW_IPS).
        ip = http_request.client.host if http_request.client else "unknown"
        return guest_identity(ip, settings.chat_identity_salt.get_secret_value())
    try:
        user_id = await run_in_threadpool(verify_user_token, credentials.credentials, settings)
        # Core owns revocation and account locks. Do not retain or send its profile to the LLM.
        response = await get_core_client().get(
            "/api/auth/me", headers={"Authorization": f"Bearer {credentials.credentials}"}
        )
        if response.status_code in {401, 403}:
            raise HTTPException(401, "Phiên đăng nhập không còn hiệu lực.")
        response.raise_for_status()
        return user_identity(user_id)
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


def rejected(error: ChatRejectedError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status,
        content={
            "code": error.code,
            "message": error.message,
            "retryAfterSeconds": error.retry_after,
            "loginRequired": error.is_login_required,
        },
        headers={"Retry-After": str(error.retry_after)},
    )


def record_usage(identity: Identity, role: str, result: LlmResult) -> None:
    # shortcut: structured log until analytics consumes the ai.usage.recorded stream (O3).
    logger.info(
        "ai.usage.recorded",
        extra={
            "feature": "chat",
            "identity": identity.key,  # user id or salted IP hash; never the message
            "role": role,
            "model": result.model_name,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost_usd": result.cost_usd,
        },
    )


@router.post(
    "/chat",
    tags=["assistant"],
    response_class=StreamingResponse,
    responses={
        200: {"content": {"text/event-stream": {}}},
        409: {"description": "TURN_IN_PROGRESS"},
        429: {"description": "RATE_LIMITED or GUEST_LIMIT_REACHED (loginRequired)"},
        503: {"description": "CHAT_BUSY"},
    },
)
async def chat(
    request: ChatRequest,
    http_request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    settings: Annotated[ChatSettings, Depends(get_chat_settings)],
    gate: Annotated[TurnGate, Depends(get_gate)],
):
    # The deadline counts from arrival, so the session check is part of the user's wait.
    deadline = asyncio.get_running_loop().time() + settings.chat_timeout_seconds
    identity = await resolve_identity(http_request, credentials, settings)
    try:
        ticket = await gate.enter(identity)
    except ChatRejectedError as error:
        return rejected(error)
    return StreamingResponse(
        run_turn(request, settings, gate, ticket, deadline),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def run_turn(
    request: ChatRequest, settings: ChatSettings, gate: TurnGate, ticket: Ticket, deadline: float
):
    usage = {"inputTokens": 0, "outputTokens": 0, "costUsd": 0.0, "estimated": True}
    try:
        yield event("status", {"step": "understanding"})
        async with asyncio.timeout_at(deadline):
            parsed = None
            llm_status = "disabled"
            if "quota" in ticket.degraded:
                llm_status = "quota"
            elif settings.chat_llm_enabled:
                yield event("status", {"step": "llm", "outcome": "calling"})
                try:
                    parsed, result = await understand(
                        request, max_turns=gate.history_turns(ticket.identity)
                    )
                    record_usage(ticket.identity, "controller", result)
                    usage.update(
                        inputTokens=result.input_tokens,
                        outputTokens=result.output_tokens,
                        costUsd=result.cost_usd,
                    )
                    llm_status = "ok"
                except LlmNotConfiguredError:
                    llm_status = "missing_config"
                except LlmUnavailableError:
                    llm_status = "breaker_open"
                except httpx.HTTPStatusError as exc:
                    llm_status = f"http_{exc.response.status_code}"
                except httpx.HTTPError:
                    llm_status = "connection_error"
                except (ValueError, KeyError, IndexError, TypeError):
                    llm_status = "invalid_response"
            yield event("status", {"step": "llm", "outcome": llm_status})
            answer = await answer_from(request, parsed)
            yield event("text", {"delta": answer.text})
            yield event(
                "cards",
                {"items": [card.model_dump(mode="json", by_alias=True) for card in answer.cards]},
            )
            yield event("done", {"kind": answer.kind, "usage": usage, "degraded": ticket.degraded})
    except (TimeoutError, httpx.HTTPError, ValidationError, ValueError):
        yield event("error", {"code": "DEPENDENCY_UNAVAILABLE", "usage": usage})
    finally:
        # Shielded: a client that leaves mid-stream cancels us, yet tokens were already spent
        # and the lock must be freed for the next turn.
        with anyio.CancelScope(shield=True):
            try:
                await gate.settle(
                    ticket,
                    tokens=usage["inputTokens"] + usage["outputTokens"],
                    cost_usd=usage["costUsd"],
                )
            finally:
                await gate.leave(ticket)


async def answer_from(request: ChatRequest, parsed) -> Answer:
    if parsed and (
        parsed.intent == "refusal"
        or (request.search_mode is None and parsed.intent in {"small_talk", "clarify"})
    ):
        if parsed.intent == "refusal":
            return Answer(
                kind="refusal", text="Mình hỗ trợ du lịch an toàn. Bạn muốn khám phá nơi nào?"
            )
        if parsed.intent == "small_talk":
            return Answer(
                kind="answer",
                text="Mình là Tripi, trợ lý du lịch của Tripflix. "
                "Mình có thể giúp bạn tìm Reel, lộ trình, khách sạn và chuyến bay.",
            )
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
        return Answer(kind="clarify", text=question)
    core = get_core_client()
    query = parsed.query if parsed else mask_pii(request.message)
    if request.search_mode == "reel":
        return await search(
            core, mask_pii(request.message.strip()), reels_only=True, fallback=parsed is None
        )
    if parsed and parsed.intent == "find_stay":
        return await search_stays(core, parsed)
    if parsed and parsed.intent == "find_flight":
        if re.search(r"\b(?:rẻ nhất|re nhat|cheapest)\b", request.message, re.I):
            parsed.cheapest_only = True
        return await search_flights(core, parsed)
    reel_request = re.match(
        r"^(?:(?:tìm|tim|cho mình xem)\s+)?(?:reels?|video)\b\s*",
        request.message.strip(),
        re.IGNORECASE,
    )
    if reel_request and parsed is None:
        query = mask_pii(request.message.strip()[reel_request.end() :])
    return await search(
        core,
        query,
        fallback=parsed is None,
        reels_only=bool(reel_request or (parsed and parsed.intent == "find_reel")),
    )
