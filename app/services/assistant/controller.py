"""What the Controller LLM may say, and how code turns it into an Understanding (v3.1).

The LLM never writes a year: live runs put 2126, 2108, 2111 into Core and Tripi then said
"sold out" for a day that had rooms (Expo Web report V11, B09). It gives day and month; code
picks the year, checks the range, and merges the turn with what Tripi remembers (trip).
"""

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel

from app.services.assistant.schemas import TripContext, Understanding

PAST_WINDOW_DAYS = 7  # "15/11" said on 16/11 means last Monday, not next year


class DayMonth(BaseModel):
    day: int
    month: int


class ControllerOutput(BaseModel):
    """Strict JSON schema for the LLM: every field present, null when not said."""

    intent: Literal[
        "search",
        "find_reel",
        "find_stay",
        "find_flight",
        "clarify",
        "refusal",
        "post_itinerary",
        "post_reviews",
        "check_room",
        "weather",
        "packing",
        "greeting",
        "identity",
        "thanks",
        "ack",
        "goodbye",
    ]
    query: str
    missing: Literal["place", "dates", "origin", "none"]
    place: str
    start: DayMonth | None
    end: DayMonth | None
    day_ref: Literal[
        "none",
        "today",
        "tomorrow",
        "this_weekend",
        "next_weekend",
        "saturday",
        "sunday",
        "yesterday",
    ]
    nights: int | None
    adults: int | None
    children: int | None
    infants: int | None
    from_airport: str | None
    to_airport: str | None
    cheapest_only: bool
    round_trip: bool
    price_max_per_night: int | None
    depart_after: str | None
    depart_before: str | None
    hotel_name: str
    card_ordinal: int | None
    reel_query: str
    uses_context_post: bool
    itinerary_day: int | None
    asks_days_count: bool
    packing_have: list[str]
    packing_only: list[str]
    packing_limit: int | None
    is_beach_trip: bool | None


def build_date(day_month: DayMonth | None, today: date) -> date | None:
    """Day and month to a date: this year, next year when long past, None when impossible."""
    if day_month is None:
        return None
    try:
        candidate = date(today.year, day_month.month, day_month.day)
    except ValueError:
        return None
    if candidate < today - timedelta(days=PAST_WINDOW_DAYS):
        try:
            candidate = date(candidate.year + 1, day_month.month, day_month.day)
        except ValueError:  # 29/02
            return None
    return candidate


def build_end(day_month: DayMonth | None, start: date | None, today: date) -> date | None:
    """Same year as the start; the next year only when the month wraps ("30/12 - 2/1").

    An end before the start in the same month stays before it, so the planner asks instead
    of silently searching another range (Expo Web report B11, D07).
    """
    if day_month is None:
        return None
    if start is None:
        return build_date(day_month, today)
    try:
        end = date(start.year, day_month.month, day_month.day)
    except ValueError:
        return None
    if end < start and day_month.month < start.month:
        try:
            end = date(start.year + 1, day_month.month, day_month.day)
        except ValueError:
            return None
    return end


def _time(value: str | None) -> str | None:
    if not value:
        return None
    parts = value.strip().replace("h", ":").split(":")
    try:
        hour, minute = int(parts[0]), int(parts[1] or 0) if len(parts) > 1 else 0
    except ValueError:
        return None
    return f"{hour:02d}:{minute:02d}" if 0 <= hour < 24 and 0 <= minute < 60 else None


def _count(value: int | None, low: int, high: int) -> int | None:
    return value if value is not None and low <= value <= high else None


def to_understanding(out: ControllerOutput, trip: TripContext | None, today: date) -> Understanding:
    trip = trip or TripContext()
    start = build_date(out.start, today)
    end = build_end(out.end, start, today)
    place = out.place.strip()
    is_new_place = bool(place) and trip.place and place.casefold() != trip.place.casefold()
    has_date_words = start is not None or out.day_ref != "none"
    # Remembered dates belong to the remembered place; a new place starts without them.
    if not has_date_words and not is_new_place:
        start, end = trip.date_from, trip.date_to
    understood = Understanding(
        intent=out.intent,
        query=out.query[:200],
        missing=out.missing if out.missing != "origin" else "none",
        place=(place or trip.place)[:100],
        check_in=start,
        check_out=end,
        flight_date=start if out.intent == "find_flight" else None,
        adults=_count(out.adults, 1, 9) or trip.adults,
        children=trip.children if out.children is None else (_count(out.children, 0, 9) or 0),
        infants=trip.infants if out.infants is None else (_count(out.infants, 0, 9) or 0),
        from_airport=out.from_airport,
        to_airport=out.to_airport,
        cheapest_only=out.cheapest_only,
        round_trip=out.round_trip,
        day_ref=out.day_ref,
        nights=_count(out.nights, 0, 30),
        uses_context_post=out.uses_context_post,
        price_max_per_night=(
            out.price_max_per_night
            if out.price_max_per_night and out.price_max_per_night > 0
            else trip.price_max_per_night
        ),
        depart_after=_time(out.depart_after),
        depart_before=_time(out.depart_before),
        hotel_name=out.hotel_name.strip()[:100],
        card_ordinal=_count(out.card_ordinal, 1, 5),
        reel_query=out.reel_query.strip()[:100],
        itinerary_day=_count(out.itinerary_day, 1, 30),
        asks_days_count=out.asks_days_count,
        packing_have=[s[:60] for s in out.packing_have[:10]],
        packing_only=[s[:60] for s in out.packing_only[:5]],
        packing_limit=_count(out.packing_limit, 1, 20),
        is_beach_trip=out.is_beach_trip,
        is_past=(start is not None and start < today) or out.day_ref == "yesterday",
    )
    if out.missing == "origin":
        understood.from_airport = None
    return understood
