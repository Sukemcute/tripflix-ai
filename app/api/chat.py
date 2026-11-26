"""POST /chat for Tripi on the mobile reel app (TF31): SSE, bounded calls, budgets per user.

Guests may chat on a small budget (Bảo, 2026-11-16); a bad or expired token is still a 401 so
the app refreshes it instead of silently dropping to the guest budget.
"""

import asyncio
import json
from contextlib import suppress
from functools import cache, partial
from typing import Annotated, Literal
from uuid import UUID, uuid4

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
from app.clients.weather import OpenMeteoWeather
from app.core.config import ChatSettings, get_chat_settings
from app.services.assistant import ChatRequest, consultant, social
from app.services.assistant.admission import (
    ChatRejectedError,
    Identity,
    RedisCounters,
    Ticket,
    TurnGate,
    guest_identity,
    user_identity,
)
from app.services.assistant.planner import today_in_vietnam
from app.services.assistant.responder import respond, split_for_stream
from app.services.assistant.schemas import TripContext
from app.services.assistant.turn import DATE_FACT, Turn
from app.services.assistant.understand import LlmNotConfiguredError, understand
from app.services.summary.pii import mask_pii
from app.services.usage_events import ChatTurn, ChatTurnEvent, ChatUsage, UsageEvent, publish_usage

__all__ = ["ChatSettings", "get_chat_settings", "router"]

router = APIRouter()
bearer = HTTPBearer(auto_error=False)
RESPONDER_SECONDS = 4.0
RESPONDER_MIN_SECONDS = 3.0  # less time left than this: keep the fixed text


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
def get_weather() -> OpenMeteoWeather:
    return OpenMeteoWeather()


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


async def consult(request: ChatRequest, trip: TripContext, **kwargs):
    """The Consultant, with provider outages seen as a failed skill (Turn then falls back)."""
    try:
        return await consultant.consult(request, trip, **kwargs)
    except (LlmNotConfiguredError, LlmUnavailableError) as exc:
        raise ValueError("consult LLM unavailable") from exc


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
    loop = asyncio.get_running_loop()
    turn_id = uuid4()
    started = deadline - settings.chat_timeout_seconds
    usage = {"inputTokens": 0, "outputTokens": 0, "costUsd": 0.0, "estimated": True}
    events: list[UsageEvent | ChatTurnEvent] = []
    parsed = None
    answer_kind = "error"
    user_id = None
    if not ticket.identity.is_guest:
        with suppress(ValueError):
            user_id = UUID(ticket.identity.key.removeprefix("user:"))
    degraded = list(ticket.degraded)
    is_llm_on = settings.chat_llm_enabled and "quota" not in degraded

    def add_usage(step: Literal["controller", "responder"], result: LlmResult) -> None:
        usage["inputTokens"] += result.input_tokens
        usage["outputTokens"] += result.output_tokens
        usage["costUsd"] += result.cost_usd
        events.append(
            UsageEvent(
                user_id=user_id,
                payload=ChatUsage(
                    conversation_id=request.conversation_id,
                    turn_id=turn_id,
                    latency_ms=result.latency_ms,
                    step=step,
                    model=result.model_name,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    cost_usd=result.cost_usd,
                ),
            )
        )

    try:
        yield event("status", {"step": "understanding"})
        async with asyncio.timeout_at(deadline):
            llm_status = "quota" if "quota" in degraded else "disabled"
            if request.action is not None:
                llm_status = "action"  # a button on a card runs as code: no LLM, no tokens
            elif is_llm_on:
                yield event("status", {"step": "llm", "outcome": "calling"})
                try:
                    parsed, _ = await understand(
                        request,
                        max_turns=gate.history_turns(ticket.identity),
                        on_usage=partial(add_usage, "controller"),
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
            yield event("status", {"step": "searching"})
            today = today_in_vietnam()
            turn = Turn(
                request,
                parsed,
                core=get_core_client(),
                weather=get_weather(),
                today=today,
                consult=(
                    partial(consult, today=today, on_usage=partial(add_usage, "responder"))
                    if is_llm_on
                    else None
                ),
                disabled_skills=frozenset(
                    name.strip()
                    for name in settings.chat_skills_disabled.split(",")
                    if name.strip()
                ),
            )
            answer = await turn.answer()
            degraded += turn.degraded
            sentences = None
            remaining = deadline - loop.time()
            if (
                is_llm_on
                and settings.chat_responder_enabled
                and parsed is not None
                and not any(
                    fact.get("type") in {consultant.CONSULT_FACT, DATE_FACT}
                    for fact in answer.facts
                )
                and answer.kind in {"answer", "no_result", "clarify"}
                and (
                    social.is_off_topic_answer(answer)
                    or answer.cards
                    or answer.facts
                    or answer.kind in {"clarify", "no_result"}
                )
                and remaining >= RESPONDER_MIN_SECONDS
            ):
                yield event("status", {"step": "writing"})
                try:
                    async with asyncio.timeout(min(RESPONDER_SECONDS, remaining - 0.5)):
                        sentences, _ = await respond(
                            request,
                            answer,
                            today=turn.today,
                            on_usage=partial(add_usage, "responder"),
                        )
                except (
                    TimeoutError,
                    LlmNotConfiguredError,
                    LlmUnavailableError,
                    httpx.HTTPError,
                    ValidationError,
                    ValueError,
                ):
                    degraded.append("responder")
            parts = sentences or split_for_stream(answer.lead or answer.text)
            for i, part in enumerate(parts):
                # The app appends deltas as they come: keep a space between sentences.
                yield event("text", {"delta": part if i == len(parts) - 1 else f"{part} "})
            yield event(
                "cards",
                {"items": [card.model_dump(mode="json", by_alias=True) for card in answer.cards]},
            )
            if answer.suggestions:
                yield event("suggestions", {"items": answer.suggestions[:4]})
            # What Tripi remembers; the app sends it back next turn (trip memory, v3.1).
            yield event("trip", turn.next_trip(answer).model_dump(mode="json", by_alias=True))
            answer_kind = answer.kind
            yield event("done", {"kind": answer.kind, "usage": usage, "degraded": degraded})
    except (TimeoutError, httpx.HTTPError, ValidationError, ValueError):
        yield event("error", {"code": "DEPENDENCY_UNAVAILABLE", "usage": usage})
    finally:
        # Shielded: a client that leaves mid-stream cancels us, yet tokens were already spent
        # and the lock must be freed for the next turn.
        with anyio.CancelScope(shield=True):
            if user_id is not None:
                events.append(
                    ChatTurnEvent(
                        user_id=user_id,
                        payload=ChatTurn(
                            conversation_id=request.conversation_id,
                            turn_id=turn_id,
                            latency_ms=max(0, round((loop.time() - started) * 1000)),
                            question=mask_pii(request.message)[:120],
                            intent=parsed.intent if parsed is not None else None,
                            answer_kind=answer_kind,
                            is_action=request.action is not None,
                        ),
                    )
                )
            try:
                await gate.settle(
                    ticket,
                    tokens=usage["inputTokens"] + usage["outputTokens"],
                    cost_usd=usage["costUsd"],
                )
            finally:
                try:
                    await gate.leave(ticket)
                finally:
                    await publish_usage(events)
