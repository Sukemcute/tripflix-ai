"""Pure rules between the Controller and the Skills: dates, clarify-once, defaults.

The LLM names a relative day ("t7 này" -> saturday) or a day and month; code turns it into
dates in Vietnam time and checks them. A range that does not make sense is asked about,
never silently replaced by another one (Expo Web report B11, B12, B16, D07, D08).
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from app.services.assistant.admission import VIETNAM
from app.services.assistant.schemas import ChatRequest, Understanding

SATURDAY, SUNDAY = 5, 6
MAX_DAYS_AHEAD = 365
FORECAST_DAYS = 16
PLAN_FIRST_CUE = r"\b(chua biet|khong biet|cu (len|xep)(?: lich| lo trinh)? truoc|len truoc)\b"
STAY_DATE_QUESTION = "Bạn muốn nhận phòng và trả phòng vào ngày nào?"
SHORT_STAY_DATES = re.compile(r"(?:(?:ngày|ngay)\s+)?([0-9]{1,2})\s+([0-9]{1,2})", re.I)


def today_in_vietnam(now: datetime | None = None) -> date:
    return (now or datetime.now(UTC)).astimezone(VIETNAM).date()


def _next_weekday(today: date, weekday: int) -> date:
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def start_day(understood: Understanding, today: date) -> date | None:
    """The first day the user means, or None when they named no day."""
    ref = understood.day_ref
    if understood.check_in:
        return understood.check_in
    if understood.flight_date:
        return understood.flight_date
    if ref == "today":
        return today
    if ref == "tomorrow":
        return today + timedelta(days=1)
    if ref == "yesterday":
        return today - timedelta(days=1)
    if ref in {"this_weekend", "saturday"}:
        # On a Sunday "this weekend" is today; otherwise the coming Saturday.
        if ref == "this_weekend" and today.weekday() == SUNDAY:
            return today
        return _next_weekday(today, SATURDAY)
    if ref == "sunday":
        return _next_weekday(today, SUNDAY)
    if ref == "next_weekend":
        return _next_weekday(today, SATURDAY) + timedelta(days=7)
    return None


@dataclass(frozen=True)
class DateProblem:
    question: str


def short_stay_dates(request: ChatRequest, today: date) -> tuple[date, date] | DateProblem | None:
    if not request.history:
        return None
    previous = request.history[-1]
    if previous.role != "assistant" or previous.text != STAY_DATE_QUESTION:
        return None
    match = SHORT_STAY_DATES.fullmatch(request.message.strip())
    if not match:
        return None
    question = DateProblem("Bạn ghi giúp mình ngày/tháng nhận phòng và ngày/tháng trả phòng nhé.")
    try:
        start, end = (today.replace(day=int(day)) for day in match.groups())
    except ValueError:
        return question
    if start < today or end <= start:
        return question
    return start, end


def stay_range(understood: Understanding, today: date) -> tuple[date, date] | DateProblem | None:
    """Nights to look up, a question to ask, or None when no day was given at all."""
    start = start_day(understood, today)
    if start is None:
        return None
    if start < today:
        return DateProblem(f"Ngày {start:%d/%m/%Y} đã qua rồi, bạn muốn nhận phòng ngày nào?")
    if start > today + timedelta(days=MAX_DAYS_AHEAD):
        return DateProblem("Tripflix chỉ nhận đặt trong 1 năm tới, bạn chọn ngày gần hơn nha.")
    end = understood.check_out
    if end is not None:
        if end == start:
            return DateProblem(
                f"Tripflix đặt phòng qua đêm. Bạn muốn trả phòng ngày nào sau {start:%d/%m}?"
            )
        if end < start:
            return DateProblem(
                f"Ngày trả {end:%d/%m} đang trước ngày nhận {start:%d/%m}. "
                "Bạn kiểm lại giúp Tripi ngày nhận và trả phòng nha."
            )
        return start, end
    if understood.nights:
        return start, start + timedelta(days=understood.nights)
    # A start day alone ("tối 21/11", "t7 này"): one night, and the answer says so (B13, B16).
    return start, start + timedelta(days=1)


@dataclass(frozen=True)
class DayWindow:
    start: date
    end: date
    is_assumed: bool  # no day was said: the next 3 days
    is_past: bool  # weather history is not available


def day_window(understood: Understanding, today: date) -> DayWindow:
    """Days to show weather or pack for: exactly the days asked, one day for a single date."""
    start = start_day(understood, today)
    if start is None:
        return DayWindow(today, today + timedelta(days=2), is_assumed=True, is_past=False)
    end = understood.check_out if understood.check_out and understood.check_out >= start else None
    if end is None and understood.nights:
        end = start + timedelta(days=understood.nights)
    end = end or start
    return DayWindow(start, end, is_assumed=False, is_past=start < today)


def has_asked_before(request: ChatRequest) -> bool:
    """Ask at most one clarifying question per conversation (TF31, DeepResearch §5.3)."""
    if request.trip and request.trip.asked:
        return True
    return any(turn.role == "assistant" and turn.kind == "clarify" for turn in request.history)
