"""What the Controller LLM may say, and how code turns it into an Understanding (v3.1).

The LLM never writes a year: live runs put 2126, 2108, 2111 into Core and Tripi then said
"sold out" for a day that had rooms (Expo Web report V11, B09). It gives day and month; code
picks the year, checks the range, and merges the turn with what Tripi remembers (trip).
"""

import re
import unicodedata
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel

from app.services.assistant.planner import PLAN_FIRST_CUE
from app.services.assistant.schemas import Awaiting, TripContext, Understanding
from app.services.summary.injection import match_injection
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
CLOSING_ONLY = (
    r"(?:(?:ok |minh )?chot(?: va dat| luon| vay)?|(?:ok )?book (?:di|lun|luon)|"
    r"dat (?:luon|di))(?: nha| nhe)?"
)
ACK_ONLY = (
    rf"(?:{CLOSING_ONLY}|(?:ok|oke|okie|okay|duoc|duoc roi|du roi|vay du roi|the thoi|"
    r"vay nhe|thoi du roi)( nha| nhe)?)"
)
DEPART_TIME = r"\b(sau|truoc) (\d{1,2}) ?(?:h|g|gio)( chieu| toi)?\b"
DAYS_COUNT_CUE = r"\b(may|bao nhieu) ngay\b"
ALREADY_HAVE = r"\bco (?:san )?([a-z ]{2,30}?) roi\b"
ITEM_LIMIT = r"\b(\d{1,2}) mon\b"
# Live eval of Controller v5 (16/11).
# "lên cho tôi lịch trình", "gợi ý lộ trình" were demoted to search with the narrower list (17/11).
PLAN_CUE = r"\b(xep|sap xep|len lich|lich trinh|lo trinh|ke hoach|plan|itinerary)\b"
THIS_REEL = r"\b(video|reel|clip) (nay|do)\b"
OFF_TOPIC_CUES = {
    "math": r"\b(lam toan|tinh giup|giai giup|giai toan|bai toan|bai tap toan|"
    r"dao ham|tich phan|phuong trinh)\b",
    "code": r"\b(viet code|lap trinh|viet ham|script|debug|"
    r"code (python|java|javascript|typescript|c\+\+|sql))\b",
    "writing": r"\b(bai van|viet van|lam van|viet tho|"
    r"bai tap (ve nha|toan|ly|hoa|tieng anh|lap trinh))\b|\btranslate\b|"
    r"\bdich(?!\s+vu\b)\s+(?:(cau|doan|bai|van ban|tu|giup)\b|"
    r"(?:\S+\s+){0,8}sang tieng\b)",
    "knowledge": r"\b(kien thuc|ai phat minh|he mat troi|quang hop|"
    r"co phieu|chung khoan|crypto)\b",
}
# "ở X" alone is also where you stay or eat ("ăn gì ở huế"): it needs a subject.
ORIGIN_CUE = (
    r"\b(?:(?:minh|em|toi|tui|tao|nha|nha minh)\s+(?:dang\s+)?o|tu|xuat phat tu|di tu)"
    r"\s+({cities})\b"
)
PICK_CUE = r"\b(?:lay|chon)\b(?:\s+\w+){0,2}?\s+(?:thu\s+)?(\d|mot|nhat|hai|ba|bon|dau tien)\b"
PICK_WORDS = {"mot": 1, "nhat": 1, "dau tien": 1, "hai": 2, "ba": 3, "bon": 4}
# Vũng Tàu report (17/11): a plan of food stops only ("lộ trình ăn uống", "chỉ quán ăn").
MEALS_CUE = (
    r"\b((lo|lich) trinh an uong|tour an uong|food tour|an uong thoi|chi (an|quan an|an uong)"
    r"|khong (xep |can )?(diem )?tham quan)\b"
)
# With a plan on screen, "chuyển thành 2n1d", "rút còn 2 ngày" change its length.
EDIT_CUE = r"\b(chuyen|doi|rut|con|thanh|xep lai|sua|giam|tang|them|bot)\b"
# Only a length, as the reply to a plan on screen: "3 ngày 2 đêm", "2n1d thôi".
DURATION_ONLY = (
    r"(\d+|mot|hai|ba|bon|nam)\s*(ngay|n)\s*((\d+|mot|hai|ba|bon)\s*(dem|d))?"
    r"( thoi| nha| nhe| di| nhe ban)?"
)
# A day the user wrote: "21/11", "ngày 21", "thứ 7", "mai", "cuối tuần".
DATE_WORDS = (
    r"\b(\d{1,2}\s*[/.-]\s*\d{1,2}|ngay \d{1,2}(?!\s*d)|thang \d{1,2}"
    r"|thu (2|3|4|5|6|7|hai|ba|tu|nam|sau|bay)"
    r"|t[2-7]|chu nhat|cn|mai|ngay mot(?! dem)|hom nay|cuoi tuan|tuan (nay|sau))\b"
)
# Live eval of v7 (17/11): the model put unsafe asks and travel questions in off_topic.
UNSAFE_CUE = (
    r"\b(thuoc ngu|thuoc (doc|chuot)|ma tuy|can sa|vu khi|sung|dao gam|tu tu|tu sat|trom"
    r"|an cap|lua dao|hack|lam bom|che tao bom|lam gia|ve gia|giay to gia|tron ve"
    r"|danh bac|ca do|mai dam)\b"
)  # [HIỆU CHỈNH]
# Chat-only injection words; the comment lexicon feeds the summary input_hash, so not there.
CHAT_INJECTION_CUE = (
    r"\b((bo qua|quen|phot lo)( \w+){0,3} (luat|quy tac|huong dan|lenh|chi dan)"
    r"|in( ra)? prompt|prompt he thong|system prompt|ignore (all|previous|the))\b"
)


def is_unsafe(message: str) -> bool:
    text = normalize_text(message)
    return bool(
        match_injection(message)
        or re.search(CHAT_INJECTION_CUE, text)
        or re.search(UNSAFE_CUE, text)
        or re.search(r"\bghi vao cau tra loi\b", text)
    )


def off_topic_kind(message: str) -> str | None:
    text = normalize_text(message)
    if re.search(r"\d\s*[+*/×÷-]\s*\d", message) and (
        re.search(r"\b(bang may|bang bao nhieu|tinh giup|giai)\b", text)
        or re.search(r"=\s*\??\s*$", message)
    ):
        return "math"
    return next((kind for kind, cue in OFF_TOPIC_CUES.items() if re.search(cue, text)), None)


TRAVEL_CUE = (
    r"\b(di dau|choi gi|an gi|uong gi|di choi|du lich|phuot|chill|check in|bien|nui|tour"
    r"|lich trinh|lo trinh)\b"
)
SUGGEST_CUE = r"\b(di dau|dau cho|cho nao|o dau|goi y|nen di)\b"
THANKS_ONLY = r"(cam on|camon|thanks|thank you|thank|tks|thanks ban)( (nha|nhe|ban|tripi|nhieu|a))*"
# A short "why" right after a reply is about that reply.
WHY_CUE = r"^(tai sao|sao (vay|the|lai|khong|ko)|vi sao|why|la sao)\b"
# A reply to Tripi's question is short: "Vũng tàu", "3 ngày 2 đêm", "từ sài gòn".
AWAIT_MAX_WORDS = 6
# An answer with both origin and day runs longer: "mình đi từ Sài Gòn, ngày 21/11" (7 words)
# was dropped and Tripi asked again (18/11) [HIỆU CHỈNH].
AWAIT_TRIP_MAX_WORDS = 10
# v5 left pace null for "đi nhiều chỗ" 3/3 (17/11) although the prompt has that very example.
PACE_CUES = {
    "packed": r"\b(di nhieu cho|nhieu cho|nhieu diem|day lich|kin lich|di het)\b",
    "relaxed": r"\b(thong tha|nhe nhang|cham rai|khong voi|chill)\b",
}
# Cities people name as a starting point, folded; the value is the name Core and the catalog know.
CITY_NAMES = {
    "sai gon": "TP.HCM", "sg": "TP.HCM", "hcm": "TP.HCM", "tp hcm": "TP.HCM", "tphcm": "TP.HCM",
    "ho chi minh": "TP.HCM", "ha noi": "Hà Nội", "hn": "Hà Nội", "da nang": "Đà Nẵng",
    "dn": "Đà Nẵng", "hai phong": "Hải Phòng", "can tho": "Cần Thơ", "hue": "Huế",
    "nha trang": "Nha Trang", "da lat": "Đà Lạt", "vung tau": "Vũng Tàu",
}  # fmt: skip


class DayMonth(BaseModel):
    day: int
    month: int


class _MessageDate(DayMonth):
    # Only code reads the user's year; the model's DayMonth schema stays unchanged.
    year: int | None = None


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
        "move_stop",
        "undo",
        "select_option",
        "confirm_booking",
        "off_topic",
        "ask_why",
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
    anchor_name: str = ""
    placement: Literal["before", "after"] | None = None
    target_day: int | None = None
    target_slot: Literal["sáng", "trưa", "chiều", "tối"] | None = None
    pace: Literal["relaxed", "packed"] | None
    meals_only: bool
    is_rude: bool


def is_harmless_off_topic(
    message: str, out: ControllerOutput | Understanding | None = None
) -> bool:
    if is_unsafe(message):
        return False
    kind = off_topic_kind(message)
    if not kind and not (out and out.intent == "off_topic"):
        return False
    text = normalize_text(message)
    travel_text = text
    # An essay's beach and a sorting exercise are not requests to plan a trip.
    if kind == "writing":
        travel_text = re.sub(r"\b(bien|nui)\b", " ", travel_text)
    elif kind == "code":
        travel_text = re.sub(r"\b(sap xep|xep)\b", " ", travel_text)
    names = (out.place, out.to_city, out.hotel_name) if out else ()
    # Remembered places copied by the Controller must not turn math into a travel request.
    named = any(name and normalize_text(name) in text for name in names)
    travel = named or any(
        re.search(cue, travel_text)
        for cue in (
            TRAVEL_CUE,
            STAY_CUE,
            PLAN_CUE,
            FLIGHT_CUE,
            WEATHER_CUE,
            PACKING_CUE,
            r"\b(chuyen bay|ve|dich vu|tour|xe)\b",
        )
    )
    return not travel


def build_date(day_month: DayMonth | None, today: date) -> date | None:
    """Day and month to a date: this year, next year when long past, None when impossible."""
    if day_month is None:
        return None
    if isinstance(day_month, _MessageDate):
        years = [day_month.year] if day_month.year else range(today.year, today.year + 5)
        for year in years:
            try:
                candidate = date(year, day_month.month, day_month.day)
            except ValueError:
                continue
            if day_month.year or candidate >= today:
                return candidate
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


def _mentioned_stops(message: str, trip: TripContext) -> list[tuple[int, int, str, str]]:
    aliases: dict[tuple[str, ...], set[str]] = {}
    for day in trip.days:
        for stop in day:
            words = normalize_text(stop.name).split()
            phrases = {
                tuple(words[start:end])
                for start in range(len(words))
                for end in range(start + 2, len(words) + 1)
            }
            phrases.update(
                tuple(normalize_text(part).split())
                for part in re.findall(r"\(([^)]+)\)", stop.name)
            )
            for phrase in phrases:
                if phrase:
                    aliases.setdefault(phrase, set()).add(stop.id)
    words = normalize_text(message).split()
    matches = []
    for start in range(len(words)):
        for end in range(start + 1, len(words) + 1):
            phrase = tuple(words[start:end])
            ids = aliases.get(phrase, set())
            if len(ids) == 1:
                matches.append((start, end, next(iter(ids)), " ".join(phrase)))
    mentioned: list[tuple[int, int, str, str]] = []
    seen: set[str] = set()
    last_end = 0
    for match in sorted(matches, key=lambda item: (item[0], item[0] - item[1])):
        start, end, stop_id, _ = match
        if start < last_end:
            continue
        last_end = end
        if stop_id not in seen:
            seen.add(stop_id)
            mentioned.append(match)
    return mentioned


def move_from_message(message: str, trip: TripContext) -> dict[str, str] | None:
    mentioned = _mentioned_stops(message, trip)
    if len(mentioned) != 2:
        return None
    words = normalize_text(message).split()
    first, second = mentioned
    placement = _visit_order(
        " ".join(words[: first[0]]), " ".join(words[first[1] : second[0]]), " ".join(words)
    )
    if placement == "swap":
        order = [stop.id for day in trip.days for stop in day]
        placement = "after" if order.index(first[2]) < order.index(second[2]) else "before"
    if placement is None:
        return None
    return {"stop_name": first[3], "anchor_name": second[3], "placement": placement}


GO = r"(?: (?:di|ghe|toi|den|qua|sang|choi|tham))?"
SEQUENCE = r"\b(sau do|roi|xong|tiep theo|tiep den|ke den|ke tiep|moi)\b"


def _visit_order(prefix: str, between: str, text: str) -> str | None:
    """Whether the first named stop comes before or after the second, from the words around.

    "A trước B", "A rồi (mới) B", "A, sau đó B", "sau A thì B" → before; "B sau A",
    "B sau khi đi A", "trước A thì đi B" → after; "đổi chỗ A và B" → swap. Order words beat
    the model's anchor: it read "Thung Lũng trước Chùa Tàu" as before German House (19/11).
    """
    if re.search(rf"\b(?:dau tien|truoc tien|truoc het){GO}$", prefix):
        return "before"
    if re.search(rf"\btruoc(?: khi)?{GO}$", prefix):
        return "after"  # "trước Chùa Tàu thì đi Thung Lũng"
    if re.search(rf"\bsau(?: khi)?{GO}$", prefix):
        return "before"  # "sau Chùa Tàu thì đi Thung Lũng"
    if re.search(r"\bsau khi\b", between):
        return "after"
    if re.search(r"\btruoc\b", between) or re.search(SEQUENCE, between):
        return "before"
    if re.search(r"\bsau\b", between):
        return "after"
    if re.fullmatch(r"(?:va|voi)", between) and re.search(r"\b(doi cho|hoan doi|dao)\b", text):
        # shortcut: swaps by moving the first past the second; exact for neighbours only.
        return "swap"
    return None


def is_unspecified_edit(message: str, trip: TripContext) -> bool:
    return bool(trip.days) and bool(
        re.fullmatch(
            r"(?:(?:toi|minh|em|tui) )?(?:(?:muon|can) )?"
            r"(?:doi|sua|xep lai)(?: lai)? (?:lich trinh|lo trinh|lich)"
            r"(?: di| nha| nhe| giup minh| giup toi)?",
            normalize_text(message),
        )
    )


def fix_plan_edit(parsed: Understanding, message: str, trip: TripContext) -> Understanding:
    if not trip.days or is_unsafe(message):
        return parsed
    mentioned = _mentioned_stops(message, trip)
    remove = None
    if len(mentioned) == 1:
        start, end, _, name = mentioned[0]
        words = normalize_text(message).split()
        context = " ".join(words[:start] + words[end:])
        accented = unicodedata.normalize("NFC", message).lower()
        # Keep accents: "bộ/bờ" are not "bỏ"; ASCII verbs must directly precede the stop.
        has_remove = (
            re.search(r"\b(bỏ|xoá|xóa|bớt|loại)\b", accented)
            or re.search(r"\bkhong (?:can )?di\b", context)
            or any(
                len(normalize_text(accented[: match.end()]).split()) == start
                for match in re.finditer(r"\b(bo|xoa|bot|loai)\b", accented)
            )
        )
        if has_remove and not re.search(
            rf"\b(truoc|sau|dau tien|doi cho|hoan doi|dao)\b|{SEQUENCE}|"
            r"\b(chuyen|doi)\b.*\b(ngay|buoi|sang|trua|chieu|toi)\b|"
            r"\bsang (ngay|buoi)\b",
            context,
        ):
            remove = {"stop_name": name, "anchor_name": "", "placement": None}
    move = move_from_message(message, trip)
    if remove or move or is_unspecified_edit(message, trip):
        return parsed.model_copy(
            update={
                "intent": "remove_stop" if remove else "move_stop" if move else "clarify",
                "place": trip.place,
                "check_in": trip.date_from,
                "check_out": trip.date_to,
                "day_ref": "none",
                "nights": None,
                "target_day": None,
                "target_slot": None,
                "missing": "none",
                **(remove or move or {}),
            }
        )
    return parsed


def to_understanding(
    out: ControllerOutput, trip: TripContext | None, today: date, *, message: str = ""
) -> Understanding:
    trip = trip or TripContext()
    start = build_date(out.start, today)
    end = build_end(out.end, start, today)
    if start and end and end <= start and out.nights:
        # "từ TP.HCM, 21/11" for a 2-night plan: the model copied the day into the end too.
        end = None
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
        flight_date=start if out.intent in {"find_flight", "change_transport"} else None,
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
        anchor_name=out.anchor_name.strip()[:120],
        placement=out.placement,
        target_day=_count(out.target_day, 1, 7),
        target_slot=out.target_slot,
        pace=out.pace,
        meals_only=out.meals_only,
        is_rude=out.is_rude,
        is_past=(start is not None and start < today) or out.day_ref == "yesterday",
    )
    if out.missing == "origin":
        understood.from_airport, understood.from_city = None, ""
    return fix_plan_edit(understood, message, trip)


def apply_guards(
    out: ControllerOutput,
    message: str,
    *,
    has_reel: bool,
    has_options: bool = False,
    in_plan: bool = False,
    has_booking: bool = False,
    awaiting: Awaiting | None = None,
) -> ControllerOutput:
    """Drop or fix what the model said that the message does not support [ĐỀ XUẤT]."""
    text = normalize_text(message)
    # The model sometimes writes the word "null" for a place nobody said (17/11).
    blanks = {
        name: ""
        for name in ("place", "from_city", "to_city")
        if normalize_text(getattr(out, name)) in {"null", "none", "n a", "khong co"}
    }
    if blanks:
        out = out.model_copy(update=blanks)
    # One name per city for the airport and route lookups: the model wrote "Sài Gòn" once and
    # "TP.HCM" the next time, and only one of them matched (18/11).
    canonical = {
        name: CITY_NAMES[normalize_text(getattr(out, name))]
        for name in ("from_city", "to_city")
        if normalize_text(getattr(out, name)) in CITY_NAMES
    }
    if canonical:
        out = out.model_copy(update=canonical)
    if re.fullmatch(GREETING, text):
        return out.model_copy(update={"intent": "greeting"})
    if re.fullmatch(THANKS_ONLY, text):  # "cam on nha" after a checklist was ack/packing (v7)
        return out.model_copy(update={"intent": "thanks"})
    if re.fullmatch(CLOSING_ONLY, text):
        return out.model_copy(update={"intent": "confirm_booking" if has_booking else "ack"})
    if re.fullmatch(ACK_ONLY, text):
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
    if out.hotel_name and re.search(THIS_REEL, normalize_text(out.hotel_name)):
        fixed["hotel_name"] = ""  # "ks trong video này…" is the reel's hotel, not a name
    if out.reel_query and re.search(THIS_REEL, text):
        # "reel đó", "video này" point at the remembered reel. v5 filled reel_query with the
        # whole sentence, "ngày cuối" or the city (chain reel-6.1, 3/5 on 17/11), and the name
        # check then said the open reel was another one.
        fixed["reel_query"] = ""
    hotel_name = fixed.get("hotel_name", out.hotel_name)
    intent = out.intent
    if intent == "confirm_booking" and not has_booking:
        named = (out.place, out.to_city, out.from_city, hotel_name, out.reel_query)
        flight_words = re.search(
            r"\b(ve|bay|may bay|chuyen bay)\b", re.sub(r"\bthu bay\b", " ", text)
        )
        has_target = (
            any(name.strip() and normalize_text(name) in text for name in named)
            or re.search(DATE_WORDS, text)
            or re.search(CALENDAR_DATE, message, re.IGNORECASE)
            or re.search(r"\b(\d+ nguoi|nguoi lon|em be|phong)\b", text)
            or re.search(STAY_CUE, text)
            or flight_words
        )
        if has_target:
            intent = "find_flight" if flight_words else "find_stay"
    cities = "|".join(sorted(CITY_NAMES, key=len, reverse=True))
    origin = re.search(ORIGIN_CUE.format(cities=cities), text)
    destination = normalize_text(out.to_city or out.place)
    if origin and destination and normalize_text(CITY_NAMES[origin.group(1)]) == destination:
        origin = None  # where you go is not where you start
    pick = re.search(PICK_CUE, text)
    # Vũng Tàu report (17/11): "chuyển thành 2n1d thôi" after a 3-day plan and "Vũng tàu" after
    # "Bạn muốn đi đâu?" were right as plan_trip, then the keyword check below sent them to search.
    # A plan on screen only shields plan_trip when the message edits it: "Đi ăn ở đâu thì
    # ngon" after a Đà Nẵng plan was plan_trip 2/3 and re-planned the trip (Bảo, 17/11).
    edits_plan = in_plan and bool(
        re.search(EDIT_CUE, text) or re.fullmatch(DURATION_ONLY, text) or re.search(MEALS_CUE, text)
    )
    plans_already = edits_plan or (awaiting is not None and awaiting.intent == "plan_trip")
    is_short = len(text.split()) <= (
        AWAIT_TRIP_MAX_WORDS
        if awaiting and awaiting.missing in {"origin", "dates", "origin_dates"}
        else AWAIT_MAX_WORDS
    )
    if (
        awaiting
        and is_short
        and (
            intent
            in {"search", "clarify", "find_stay", "find_reel", "find_flight", "change_transport"}
            or intent == "plan_trip"
            or (awaiting.intent == "plan_trip" and re.search(PLAN_FIRST_CUE, text))
        )
    ):
        reply_city = out.from_city or (CITY_NAMES[origin.group(1)] if origin else "")
        if not reply_city and awaiting.missing in {"origin", "origin_dates"}:
            reply_city = next(
                (
                    name
                    for name in (out.place, out.to_city)
                    if name and normalize_text(name) in text
                ),
                "",
            )
        calendar_date = re.search(CALENDAR_DATE, message, re.IGNORECASE)
        if (
            awaiting.missing in {"dates", "origin_dates", "origin"}
            and out.start is None
            and calendar_date
        ):
            day, month = map(int, re.findall(r"\d+", calendar_date.group()))
            year = re.match(r"\s*[/.-]\s*(\d{4})\b", message[calendar_date.end() :])
            fixed["start"] = _MessageDate(
                day=day, month=month, year=int(year.group(1)) if year else None
            )
        elif awaiting.missing in {"dates", "origin_dates"} and out.day_ref == "none":
            relative_days = DAY_CUES | {
                "next_weekend": r"\bcuoi tuan sau\b",
                "this_weekend": r"\bcuoi tuan(?! sau)\b",
                "saturday": r"\b(t7|thu (7|bay))\b",
                "sunday": r"\b(chu nhat|cn)\b",
            }
            for day_ref, cue in relative_days.items():
                if re.search(cue, text):
                    fixed["day_ref"] = day_ref
                    break
        has_date = bool(
            out.start is not None
            or out.day_ref != "none"
            or out.nights is not None
            or calendar_date
            or re.search(DATE_WORDS, text)
        )
        fills = {
            "place": bool(out.place),
            "dates": (
                out.start is not None
                or out.day_ref != "none"
                or out.nights is not None
                or calendar_date is not None
                or re.search(DATE_WORDS, text) is not None
            ),
            "origin": bool(reply_city) or (awaiting.intent == "plan_trip" and has_date),
            "origin_dates": bool(reply_city) or has_date,
        }[awaiting.missing]
        if fills or (awaiting.intent == "plan_trip" and re.search(PLAN_FIRST_CUE, text)):
            intent = awaiting.intent  # the answer to Tripi's question finishes that request
            if awaiting.missing in {"origin", "origin_dates"} and reply_city:
                fixed |= {"from_city": reply_city, "place": "", "to_city": "", "missing": "none"}
            if out.nights is None and awaiting.nights is not None:
                fixed["nights"] = awaiting.nights
            if awaiting.intent == "plan_trip":
                fixed["query"] = message
                if reply_city:
                    fixed |= {
                        "from_city": reply_city,
                        "place": "",
                        "to_city": "",
                        "missing": "none",
                    }
    if (
        in_plan
        and out.nights is not None
        and intent in {"search", "find_stay", "clarify"}
        and (re.search(EDIT_CUE, text) or re.fullmatch(DURATION_ONLY, text))
    ):
        intent = "plan_trip"
    if is_short and intent in {"clarify", "search", "refusal"} and re.search(WHY_CUE, text):
        intent = "ask_why"
    if intent == "ask_why" and not re.search(r"\b(tai sao|vi sao|sao|why)\b", text):
        # "vậy đi biển đâu cho chill" came back as ask_why once (17/11): no "why", no ask_why.
        intent = "search" if re.search(TRAVEL_CUE, text) or out.place else "clarify"
    if intent == "off_topic":
        # Unsafe asks, prompt injection and homework stay refused; travel asks stay travel.
        if is_unsafe(message) or (off_topic_kind(message) and is_harmless_off_topic(message, out)):
            intent = "refusal"
        elif re.search(PACKING_CUE, text):
            intent = "packing"
        elif re.search(STAY_CUE, text):
            intent = "find_stay"
        elif re.search(WEATHER_CUE, text):
            intent = "weather"
        elif out.place or re.search(TRAVEL_CUE, text):
            intent = "search"
    if has_options and pick and intent != "select_option":
        intent = "select_option"  # "lấy cái thứ 1" with options on screen was change_stay 3/3
        word = pick.group(1)
        fixed["card_ordinal"] = int(word) if word.isdigit() else PICK_WORDS[word]
    elif (
        intent in {"plan_trip", "search", "find_stay", "clarify"}
        and origin
        and not (awaiting and awaiting.intent == "plan_trip")
        and not re.search(STAY_CUE, text)
        and not re.search(PLAN_CUE, text)
    ):
        intent = "change_transport"  # "mình ở sài gòn" after a plan was plan_trip 3/3 (v5)
    elif intent == "post_itinerary" and re.search(r"\bthoi tiet\b", text):
        intent = "weather"  # "Thời tiết Đà Lạt thứ Bảy" while a reel is open
    elif intent == "refusal" and re.search(IDENTITY_CUE, text):
        intent = "identity"  # "ban lam duoc gi" was refused 3/3
    elif (
        intent == "refusal"
        and (out.from_airport or out.from_city)
        and (out.to_airport or out.to_city)
    ):
        intent = "find_flight"  # flight-02: both airports read, then refused
    elif intent in {"search", "find_reel"} and is_harmless_off_topic(message, out):
        intent = "refusal"  # "làm giúp bài văn tả cảnh biển" was a search 2/3 (v5)
    elif intent == "plan_trip" and not plans_already and not re.search(PLAN_CUE, text):
        # "muốn đi vũng tàu 2n1đ", "đặt phòng giúp mình" are not "plan it for me" (v5).
        intent = "find_stay" if re.search(STAY_CUE, text) else "search" if out.place else "clarify"
        if intent == "clarify":
            fixed["missing"] = "place"
    elif intent in {"find_reel", "search"} and (
        (has_reel and out.uses_context_post) or re.search(THIS_REEL, text)
    ):
        # "video này ở đâu vậy" in a reel was find_reel 3/3. "Video này" names one reel even
        # when none is open (trip-03, 0/3 on 17/11): the itinerary step then asks to open it.
        intent = "post_itinerary"
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
    elif (
        intent == "clarify"
        and not out.place
        and re.search(SUGGEST_CUE, text)
        and re.search(TRAVEL_CUE, text)
    ):
        intent = "search"  # "vậy đi biển đâu cho chill" asks for ideas, not to be asked back
    elif intent in {"search", "clarify"} and out.place and re.search(STAY_CUE, text):
        intent = "find_stay"
    elif (
        intent in {"packing", "find_stay", "search"}
        and re.search(WEATHER_CUE, text)
        and not re.search(PACKING_CUE, text)
        and not re.search(STAY_CUE, text)
    ):
        intent = "weather"  # W14 "mai da lat co mua k"
    if (
        in_plan
        and out.stop_name.strip()
        and (
            (out.anchor_name.strip() and re.search(r"\b(truoc|sau)\b", text))
            or re.search(
                r"\b(chuyen|doi|de)\b.*\b(ngay\s+\d+|buoi\s+(sang|trua|chieu|toi))\b", text
            )
        )
    ):
        intent = "move_stop"
    if intent == "refusal" and not is_unsafe(message):
        # social imports Controller cues; defer this import to avoid the cycle.
        from app.services.assistant.social import has_abuse  # noqa: PLC0415

        named = (out.place, out.to_city, out.from_city, hotel_name, out.reel_query)
        has_target = any(name.strip() and normalize_text(name) in text for name in named)
        has_target = bool(
            has_target or re.search(DATE_WORDS, text) or re.search(CALENDAR_DATE, message)
        )
        if (out.is_rude or has_abuse(message)) and has_target:
            if re.search(STAY_CUE, text):
                intent = "find_stay"
            elif re.search(FLIGHT_CUE, re.sub(r"\bthu bay\b", " ", text)):
                intent = "find_flight"
            elif re.search(PLAN_CUE, text):
                intent = "plan_trip"
            elif re.search(TRAVEL_CUE, text):
                intent = "search"
    if intent != out.intent:
        fixed["intent"] = intent
        if out.missing == "dates" and intent in {"find_stay", "weather"}:
            fixed["missing"] = "none"
    if intent == "move_stop":
        # A numbered plan day is not a new travel date or destination.
        fixed |= {"start": None, "end": None, "day_ref": "none", "place": "", "nights": None}
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
    is_trip_leg = intent in {"change_transport", "find_flight"}
    if is_trip_leg and origin:
        if not out.from_city:
            fixed["from_city"] = CITY_NAMES[origin.group(1)]  # "mình ở sài gòn": 0/3 with v5
        if out.missing == "origin":
            # The origin was said; else to_understanding drops it (v5 gave SGN + missing=origin).
            fixed["missing"] = "none"
    said_date = re.search(DATE_WORDS, text) or re.search(CALENDAR_DATE, message, re.IGNORECASE)
    if (out.start or out.end) and not said_date:
        # "2 ngày 1 đêm" alone got today as the start (Vũng Tàu report P2): no date was said,
        # so the trip keeps the dates it already had.
        fixed |= {"start": None, "end": None}
    if intent == "plan_trip" and not out.meals_only and re.search(MEALS_CUE, text):
        fixed["meals_only"] = True
    if intent == "plan_trip" and out.pace is None:
        fixed["pace"] = next((p for p, cue in PACE_CUES.items() if re.search(cue, text)), None)
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
    if is_unsafe(message) or (off_topic_kind(message) and is_harmless_off_topic(message, out)):
        fixed["intent"] = "refusal"
    return out.model_copy(update=fixed) if fixed else out
