"""What the Controller LLM may say, and how code turns it into an Understanding (v3.1).

The LLM never writes a year: live runs put 2126, 2108, 2111 into Core and Tripi then said
"sold out" for a day that had rooms (Expo Web report V11, B09). It gives day and month; code
picks the year, checks the range, and merges the turn with what Tripi remembers (trip).
"""

import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel

from app.services.assistant.schemas import TripContext, Understanding
from app.services.summary.vi_text import normalize_text

PAST_WINDOW_DAYS = 7  # "15/11" said on 16/11 means last Monday, not next year

# Words that must be in the message before code believes a slot (live eval 2026-11-16: the
# model wrote day_ref "today" for messages naming no day, round trips nobody asked for, and
# hotel names nobody said). Matched on accent-free text.
DAY_CUES = {
    "today": r"\b(hom nay|hnay|bua nay|(toi|sang|chieu|trua|dem) nay|bay gio|luc nay)\b",
    "tomorrow": r"\b(mai|ngay mai)\b",
    "yesterday": r"\b(hom qua)\b",
}
ROUND_TRIP_CUE = r"\b(khu hoi|(2|hai) chieu|chieu ve|round ?trip)\b"
INFANT_CUE = r"\b(em be|so sinh|infants?)\b"
STAY_CUE = (
    r"\b(ks|khach san|homestay|resort|nha nghi|villa|hostel|cho o|cho ngu|"
    r"(con|dat|nhan|tra|thue) phong)\b"
)
WEATHER_CUE = (
    r"\b(thoi tiet|du bao|nhiet do|co mua|mua (khong|k|ko)|troi mua|"
    r"(nang|lanh|nong) (khong|k|ko))\b"
)
PACKING_CUE = r"\b(mang|mac|chuan bi|do gi|ao|vali|hanh ly|checklist)\b"
ITINERARY_DAY = r"\bngay (?:thu )?(\d{1,2}|nhat|mot|hai|ba|bon|tu|nam|sau|bay)\b"
DAY_WORDS = {
    "nhat": 1, "mot": 1, "hai": 2, "ba": 3, "bon": 4, "tu": 4, "nam": 5, "sau": 6, "bay": 7,
}  # fmt: skip
SOCIAL_INTENTS = {"greeting", "thanks", "ack", "goodbye"}
MAX_SOCIAL_WORDS = 6
IDENTITY_CUE = r"\b(la ai|(lam|giup) (duoc )?(gi|nhung gi)|biet lam gi)\b"


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


def apply_guards(out: ControllerOutput, message: str, *, has_reel: bool) -> ControllerOutput:
    """Drop or fix what the model said that the message does not support [ĐỀ XUẤT]."""
    text = normalize_text(message)
    fixed: dict = {}
    if out.day_ref in DAY_CUES and not re.search(DAY_CUES[out.day_ref], text):
        fixed["day_ref"] = "none"
    if out.round_trip and not re.search(ROUND_TRIP_CUE, text):
        fixed["round_trip"] = False
    if out.children and not out.infants and re.search(INFANT_CUE, text):
        fixed["children"], fixed["infants"] = None, out.children
    name_words = [w for w in normalize_text(out.hotel_name).split() if len(w) > 1]
    if name_words and not all(re.search(rf"\b{re.escape(w)}\b", text) for w in name_words):
        fixed["hotel_name"] = ""
    hotel_name = fixed.get("hotel_name", out.hotel_name)
    intent = out.intent
    if intent == "refusal" and re.search(IDENTITY_CUE, text):
        intent = "identity"  # "ban lam duoc gi" was refused 3/3
    elif intent == "refusal" and out.from_airport and out.to_airport:
        intent = "find_flight"  # flight-02: both airports read, then refused
    elif intent == "check_room" and not hotel_name and not has_reel:
        intent = "find_stay"  # no reel to read a hotel from: the user means stays there
    elif intent in SOCIAL_INTENTS and len(text.split()) > MAX_SOCIAL_WORDS:
        intent = "search"  # a long message is never only "ok" (review-02)
    elif intent in {"search", "clarify"} and out.place and re.search(STAY_CUE, text):
        intent = "find_stay"
    elif (
        intent in {"packing", "find_stay", "search"}
        and re.search(WEATHER_CUE, text)
        and not re.search(PACKING_CUE, text)
        and not re.search(STAY_CUE, text)
    ):
        intent = "weather"  # W14 "mai da lat co mua k"
    if intent != out.intent:
        fixed["intent"] = intent
        if out.missing == "dates" and intent in {"find_stay", "weather"}:
            fixed["missing"] = "none"
    if intent == "post_itinerary" and out.itinerary_day is None:
        found = re.search(ITINERARY_DAY, text)
        if found:
            word = found.group(1)
            fixed["itinerary_day"] = int(word) if word.isdigit() else DAY_WORDS[word]
    if intent == "post_itinerary":
        # A reel's days are numbered from 1; a date here would only be "ngay 2" misread.
        fixed |= {"start": None, "end": None, "day_ref": "none"}
    return out.model_copy(update=fixed) if fixed else out
