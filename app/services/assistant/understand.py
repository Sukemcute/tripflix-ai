"""Controller step of a chat turn: one LLM call that turns the message into JSON (TF31).

The LLM sees only the masked message and recent turns, never Core results. Each role has its
own adapter and breaker (Bảo, 2026-11-16: Controller on OpenAI, Responder on DeepSeek).
"""

import json
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, time
from functools import cache
from pathlib import Path
from typing import Any, Literal

from app.clients.llm.base import LlmResult
from app.clients.llm.deepseek import DeepSeekClient
from app.clients.llm.fake import FakeLlmClient
from app.clients.llm.guarded import GuardedLlmClient
from app.clients.llm.openai import OpenAILlmClient
from app.core.breaker import CircuitBreaker
from app.core.config import get_chat_settings
from app.services.assistant.admission import VIETNAM
from app.services.assistant.calendar import WEEKDAYS_VI, build_calendar, now_in_vietnam
from app.services.assistant.controller import (
    ControllerOutput,
    apply_guards,
    controller_json_schema,
    empty_output,
    has_date_cue,
    rules_intent,
    to_understanding,
)
from app.services.assistant.controller_prompt import (
    build_system_prompt,
    needed_module,
    select_modules,
)
from app.services.assistant.schemas import ChatRequest, Understanding
from app.services.assistant.turn import REEL_KINDS
from app.services.summary.injection import match_injection
from app.services.summary.pii import mask_pii

logger = logging.getLogger(__name__)
# Empty trip fields are dropped from the input (tokens); these two are sent whenever set.
ALWAYS_SENT_TRIP_FIELDS = {"adults", "priceMaxPerNight"}
Role = Literal["controller", "responder"]
RULES_MODEL = "rules"  # model_name of a turn that code decided without an LLM call
# v13 is one block; the per-turn prompt is controller_prompt (core + modules). Kept as the
# fallback the eval compares against.
PROMPT = Path(__file__).parents[2] / "prompts" / "assistant-controller.v13.md"


class LlmNotConfiguredError(Exception):
    pass


def resolve_now(now: datetime | None, today: date | None) -> datetime:
    """The turn's clock; a bare `today` (tests, fixed days) means 08:00 that day."""
    if now is not None:
        return now
    return datetime.combine(today, time(8, 0), VIETNAM) if today else now_in_vietnam()


def trip_input(fields: dict[str, Any]) -> dict[str, Any]:
    """Only what is set: null, empty, 0 and false say nothing the model needs."""
    return {
        key: value
        for key, value in fields.items()
        if (
            value is not None
            if key in ALWAYS_SENT_TRIP_FIELDS
            else value not in (None, [], "", 0, False)
        )
    }


def build_understanding_input(
    request: ChatRequest,
    *,
    max_turns: int = 6,
    today: date | None = None,
    now: datetime | None = None,
) -> str:
    now = resolve_now(now, today)
    today = now.date()
    trip = request.trip
    return json.dumps(
        {
            "today": f"{today.isoformat()} ({WEEKDAYS_VI[today.weekday()]})",
            # Real days, weekends and holidays: the model reads dates here, never computes them.
            # Only when the turn talks about dates (~680 tokens); relative_dates still checks after.
            **({"calendar": build_calendar(now)} if has_date_cue(request.message, trip) else {}),
            # Only whether a reel is in view: its id never reaches the LLM.
            "hasContextPost": request.context_post_id is not None,
            # What Tripi remembers, without ids or user-written titles (trusted fields only).
            "trip": None
            if trip is None
            else trip_input(
                {
                    "place": trip.place,
                    "dateFrom": trip.date_from.isoformat() if trip.date_from else None,
                    "dateTo": trip.date_to.isoformat() if trip.date_to else None,
                    "adults": trip.adults,
                    "priceMaxPerNight": trip.price_max_per_night,
                    "hasReel": trip.reel_id is not None,
                    "lastCards": [
                        {"ref": c.ref, "kind": c.kind}
                        | ({"price": c.price} if c.kind == "stay" and c.price is not None else {})
                        for c in trip.last_cards
                    ],
                    # Stage B plan: names from Core and OSM, never ids or user-written titles.
                    "originCity": trip.origin_city,
                    "stay": trip.stay.name if trip.stay else None,
                    "planDays": len(trip.days),
                    "planStops": [stop.name for day in trip.days for stop in day][:20],
                    "interests": trip.interests,
                    "mealsOnly": trip.meals_only,
                    "prefs": trip.prefs.model_dump(mode="json", by_alias=True)
                    if trip.prefs
                    else None,
                    "pendingCount": len(trip.pending_flights or trip.pending),
                    "hasChosenFlight": bool(trip.transport and trip.transport.flight_id),
                    # What Tripi just asked for: a short reply ("Vũng tàu") finishes this request.
                    "awaiting": trip.awaiting.model_dump(mode="json", by_alias=True)
                    if trip.awaiting
                    else None,
                }
            ),
            # Rules that caught injection in comments (TF44) tag the message; the Controller
            # still only names an intent, so the tag is a hint plus a log line, not a block.
            "suspectedInjection": bool(match_injection(request.message)),
            "history": [
                {"role": turn.role, "text": mask_pii(turn.text)}
                for turn in request.history[-max_turns:]
            ],
            # Latest last: with history after it, v5 answered the user's previous message
            # (chain vung-tau-0A2, 3/3 on 17/11; 2/2 right once moved here).
            "message": mask_pii(request.message),
        },
        ensure_ascii=False,
    )


@cache
def get_role_llm(role: Role) -> GuardedLlmClient:
    """One client per role per process, so connections and the breaker are shared."""
    settings = get_chat_settings()
    provider = getattr(settings, f"chat_{role}_provider")
    model = getattr(settings, f"chat_{role}_model")
    limits = {"timeout_seconds": settings.chat_llm_timeout_seconds, "max_attempts": 1}
    if provider == "fake":
        inner = FakeLlmClient()
    elif provider == "openai":
        prices = {
            "input": getattr(settings, f"chat_{role}_price_input"),
            "cached_input": getattr(settings, f"chat_{role}_price_cached_input"),
            "output": getattr(settings, f"chat_{role}_price_output"),
        }
        if not settings.openai_api_key.get_secret_value() or not model:
            raise LlmNotConfiguredError(f"{role}: OPENAI_API_KEY and model are required")
        if any(value is None for value in prices.values()):
            raise LlmNotConfiguredError(f"{role}: the three CHAT_*_PRICE_* are required")
        inner = OpenAILlmClient(
            settings.openai_api_key,
            model=model,
            prices={name: float(value) for name, value in prices.items() if value is not None},
            base_url=settings.openai_base_url,
            reasoning_effort=settings.openai_reasoning_effort,
            max_output_tokens=settings.chat_max_output_tokens,
            **limits,
        )
    else:
        if not settings.deepseek_api_key.get_secret_value():
            raise LlmNotConfiguredError(f"{role}: DEEPSEEK_API_KEY is required")
        inner = DeepSeekClient(
            settings.deepseek_api_key,
            model=model,
            base_url=settings.deepseek_base_url,
            max_output_tokens=settings.chat_max_output_tokens,
            **limits,
        )
    return GuardedLlmClient(inner, CircuitBreaker(f"chat-{role}"))


async def call_controller(
    system: str, user_input: str, on_usage: Callable[[LlmResult], None] | None
) -> tuple[LlmResult, ControllerOutput]:
    result = await get_role_llm("controller").agenerate(
        system, user_input, controller_json_schema()
    )
    if on_usage is not None:
        on_usage(result)
    # A cut JSON can still parse into something wrong; never trust it.
    if result.finish_reason == "length":
        raise ValueError("controller output was cut")
    return result, ControllerOutput.model_validate_json(result.output)


async def understand(
    request: ChatRequest,
    *,
    max_turns: int,
    on_usage: Callable[[LlmResult], None] | None = None,
    now: datetime | None = None,
) -> tuple[Understanding, LlmResult]:
    """Raises on provider errors, cut output or invalid JSON: the caller falls back."""
    groups = match_injection(request.message)
    if groups:  # rule names only, never the message
        logger.warning("chat.injection.suspected", extra={"groups": groups})
    now = resolve_now(now, None)
    if (intent := rules_intent(request.message)) is not None:
        # apply_guards would force this intent anyway: no tokens, no usage event.
        result = LlmResult(
            output="",
            model_name=RULES_MODEL,
            input_tokens=0,
            output_tokens=0,
            finish_reason="stop",
            latency_ms=0,
        )
        out = empty_output(intent)
    else:
        user_input = build_understanding_input(request, max_turns=max_turns, now=now)
        modules = select_modules(request, has_date_cue=has_date_cue(request.message, request.trip))
        result, out = await call_controller(build_system_prompt(modules), user_input, on_usage)
        # The model named an intent whose rules are in a module this turn did not load.
        missing = needed_module(out)
        is_recalled = missing is not None and missing not in modules
        if missing is not None and is_recalled:
            modules = modules | {missing}
            second, out = await call_controller(build_system_prompt(modules), user_input, on_usage)
            result = replace(
                second,
                input_tokens=result.input_tokens + second.input_tokens,
                output_tokens=result.output_tokens + second.output_tokens,
                cost_usd=result.cost_usd + second.cost_usd,
                latency_ms=(result.latency_ms or 0) + (second.latency_ms or 0),
            )
        # Module names only, never the message.
        logger.info(
            "chat.controller.modules", extra={"modules": sorted(modules), "recalled": is_recalled}
        )
    trip = request.trip
    has_reel = bool(
        request.context_post_id
        or (trip and (trip.reel_id or any(c.kind in REEL_KINDS for c in trip.last_cards)))
    )
    out = apply_guards(
        out,
        request.message,
        has_reel=has_reel,
        has_options=bool(trip and (trip.pending or trip.pending_flights)),
        in_plan=bool(trip and trip.days),
        has_booking=bool(
            trip
            and (
                (trip.stay and trip.stay.source == "tripflix")
                or (trip.transport and trip.transport.flight_id)
            )
        ),
        awaiting=trip.awaiting if trip else None,
        today=now.date(),
        trip_place=trip.place if trip else "",
    )
    return to_understanding(out, trip, now.date(), message=request.message), result
