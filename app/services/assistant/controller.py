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
EXPLICIT_WEATHER_DAYS = {"hom nay": "today", "ngay mai": "tomorrow", "hom qua": "yesterday"}
CALENDAR_DATE = r"\b\d{1,2}(?:\s*[/.-]\s*|\s+th[aá]ng\s+)\d{1,2}\b"
GREETING = r"(?:hi+|hell?o+|hey+|(?:xin )?chao(?: ban| tripi)?)"
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
# Live eval of v4 (16/11): slots the message states plainly but the model sometimes missed.
FLIGHT_CUE = r"\b(bay|may bay|ve bay|chuyen bay|flight|san bay)\b"  # after "thu bay" is removed
ACK_ONLY = (
    r"(ok|oke|okie|okay|duoc|duoc roi|du roi|vay du roi|chot|chot vay|minh chot vay|the thoi|"
    r"vay nhe|thoi du roi)( nha| nhe)?"
)
DEPART_TIME = r"\b(sau|truoc) (\d{1,2}) ?(?:h|g|gio)( chieu| toi)?\b"
DAYS_COUNT_CUE = r"\b(may|bao nhieu) ngay\b"
ALREADY_HAVE = r"\bco (?:san )?([a-z ]{2,30}?) roi\b"
ITEM_LIMIT = r"\b(\d{1,2}) mon\b"


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
        # Stage B (plan B7): plan the whole trip and edit it
        "plan_trip",
        "change_stay",
        "change_transport",
        "remove_stop",
        "undo",
        "select_option",
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
    from_city: str
    to_city: str
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
    interests: list[str]
    stop_name: str
    pace: Literal["relaxed", "packed"] | None


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
        from_city=out.from_city.strip()[:60],
        to_city=out.to_city.strip()[:60],
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
        interests=[s[:30] for s in out.interests[:5]],
        stop_name=out.stop_name.strip()[:120],
        pace=out.pace,
        is_past=(start is not None and start < today) or out.day_ref == "yesterday",
    )
    if out.missing == "origin":
        understood.from_airport, understood.from_city = None, ""
    return understood


def apply_guards(out: ControllerOutput, message: str, *, has_reel: bool) -> ControllerOutput:
    """Drop or fix what the model said that the message does not support [ĐỀ XUẤT]."""
    text = normalize_text(message)
    if re.fullmatch(GREETING, text):
        return out.model_copy(update={"intent": "greeting"})
    if re.fullmatch(ACK_ONLY, text):  # "mình chốt vậy" after a checklist was read as packing
        return out.model_copy(update={"intent": "ack"})
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
    elif (
        intent == "refusal"
        and (out.from_airport or out.from_city)
        and (out.to_airport or out.to_city)
    ):
        intent = "find_flight"  # flight-02: both airports read, then refused
    elif intent in {"find_reel", "search"} and has_reel and out.uses_context_post:
        intent = "post_itinerary"  # "video này ở đâu vậy" in a reel was find_reel 3/3
    elif intent == "check_room" and not hotel_name and not has_reel:
        intent = "find_stay"  # no reel to read a hotel from: the user means stays there
    elif (
        intent == "find_flight"
        and re.search(STAY_CUE, text)
        and not re.search(FLIGHT_CUE, re.sub(r"\bthu bay\b", " ", text))
    ):
        intent = "find_stay"  # "ks da nang t7 nay" was read as a flight 3/3 with v4
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
    if intent in {"weather", "packing"} and not re.search(CALENDAR_DATE, message, re.IGNORECASE):
        explicit_days = {
            day
            for phrase, day in EXPLICIT_WEATHER_DAYS.items()
            if re.search(rf"\b{phrase}\b", text)
        }
        if len(explicit_days) == 1:
            # An explicit relative day in the latest message beats remembered or invented dates.
            fixed |= {"day_ref": explicit_days.pop(), "start": None}
    if intent == "post_itinerary" and out.itinerary_day is None:
        found = re.search(ITINERARY_DAY, text)
        if found:
            word = found.group(1)
            fixed["itinerary_day"] = int(word) if word.isdigit() else DAY_WORDS[word]
    if intent == "post_itinerary":
        # A reel's days are numbered from 1; a date here would only be "ngay 2" misread.
        fixed |= {"start": None, "end": None, "day_ref": "none"}
        if re.search(DAYS_COUNT_CUE, text):
            fixed["asks_days_count"] = True
    if intent == "find_flight":
        said: dict[str, str] = {}
        for word, hour, part in re.findall(DEPART_TIME, text):
            clock = int(hour) + (12 if part and int(hour) < 12 else 0)
            if clock < 24:
                said["depart_after" if word == "sau" else "depart_before"] = f"{clock:02d}:00"
        if said:  # the message names the time window: it wins over the model's reading
            fixed |= {"depart_after": None, "depart_before": None} | said
    if intent == "packing":
        if not out.packing_have and (have := re.search(ALREADY_HAVE, text)):
            fixed["packing_have"] = [have.group(1).strip()]
        if out.packing_limit is None and (limit := re.search(ITEM_LIMIT, text)):
            fixed["packing_limit"] = int(limit.group(1))
        only = [o for o in out.packing_only if not re.fullmatch(ITEM_LIMIT, normalize_text(o))]
        if only != out.packing_only:
            fixed["packing_only"] = only
    return out.model_copy(update=fixed) if fixed else out
