"""Controller system prompt = fixed core + skill modules that code picks per turn (TF31).

The cache prefix stays stable: modules are always joined in MODULE_ORDER, and nothing that
changes per turn (dates, trip) ever goes into the system prompt.
"""

import re
from functools import cache
from pathlib import Path

from app.services.assistant.controller import (
    CLOSING_ONLY,
    COMPARE_CUE,
    CONSULT_CUE,
    STAY_CUE,
    ControllerOutput,
)
from app.services.assistant.schemas import ChatRequest
from app.services.assistant.turn import REEL_KINDS
from app.services.summary.vi_text import normalize_text

PROMPT_DIR = Path(__file__).parents[2] / "prompts" / "controller"
CORE_VERSION = "v1"
MODULE_ORDER: tuple[str, ...] = (
    "calendar",
    "stay_filters",
    "plan_edit",
    "reel",
    "booking_options",
    "consult",
)
MODULE_VERSIONS: dict[str, str] = dict.fromkeys(MODULE_ORDER, "v1")
# The intent whose rules and examples live in a module; a reply that needs a module the first
# call did not have is asked again with it. find_stay needs stay_filters only with a filter slot.
INTENT_MODULES: dict[str, str] = {
    "post_itinerary": "reel",
    "post_reviews": "reel",
    "move_stop": "plan_edit",
    "remove_stop": "plan_edit",
    "select_option": "booking_options",
    "confirm_booking": "booking_options",
    "consult": "consult",
}


# Live eval (27/11): "từ 1tr đến 2tr một đêm" and "chuyển Chợ Hàn sang ngày 2" carry no stay word
# and no plan in the trip, yet their slot rules live in a module; the cue loads it.
PRICE_CUE = r"\b\d+(?:[.,]\d+)? ?(?:tr|k)\b"
MOVE_CUE = r"\b(?:chuyen|doi|dua|bo|xoa)\b.*\b(?:sang|truoc|sau|buoi)\b"


def select_modules(request: ChatRequest, *, has_date_cue: bool) -> frozenset[str]:
    """Which modules this turn may need, from conversation state and cues in the message."""
    text = normalize_text(request.message)
    trip = request.trip
    cards = trip.last_cards if trip else []
    is_booked = bool(
        trip
        and (
            (trip.stay and trip.stay.source == "tripflix")
            or (trip.transport and trip.transport.flight_id)
        )
    )
    flags = {
        "calendar": has_date_cue,
        "stay_filters": any(c.kind == "stay" for c in cards)
        or bool(re.search(f"{STAY_CUE}|{COMPARE_CUE}|{PRICE_CUE}", text)),
        "plan_edit": bool(trip and trip.days) or bool(re.search(MOVE_CUE, text)),
        "reel": bool(
            request.context_post_id
            or (trip and trip.reel_id)
            or any(c.kind in REEL_KINDS for c in cards)
        ),
        "booking_options": bool(trip and (trip.pending or trip.pending_flights))
        or is_booked
        or bool(re.search(rf"\b(?:{CLOSING_ONLY})\b", text)),
        "consult": bool(re.search(CONSULT_CUE, text)) or bool(trip and trip.prefs),
    }
    return frozenset(name for name, is_needed in flags.items() if is_needed)


@cache
def read_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8").strip()


def build_system_prompt(modules: frozenset[str]) -> str:
    parts = [read_prompt(f"core.{CORE_VERSION}.md")]
    parts += [
        read_prompt(f"modules/{name}.{MODULE_VERSIONS[name]}.md")
        for name in MODULE_ORDER
        if name in modules
    ]
    return "\n\n".join(parts)


def needed_module(out: ControllerOutput) -> str | None:
    if out.intent == "find_stay" and (
        out.stay_sort != "none"
        or out.price_relative != "none"
        or out.min_stars is not None
        or out.price_min_per_night is not None
    ):
        return "stay_filters"
    return INTENT_MODULES.get(out.intent)
