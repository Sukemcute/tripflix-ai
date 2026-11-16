"""Pure rules between the Controller and the Skills: dates, clarify-once, defaults.

The LLM names a relative day ("t7 này" -> saturday); code turns it into a date in Vietnam
time, so "this Saturday" is the same answer whatever model runs (DeepResearch §5.3).
"""

from datetime import UTC, date, datetime, timedelta

from app.services.assistant.admission import VIETNAM
from app.services.assistant.schemas import ChatRequest, Understanding

SATURDAY, SUNDAY = 5, 6


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
    if ref in {"this_weekend", "saturday"}:
        # On a Sunday "this weekend" is today; otherwise the coming Saturday.
        return (
            today
            if ref == "this_weekend" and today.weekday() == SUNDAY
            else (_next_weekday(today, SATURDAY))
        )
    if ref == "sunday":
        return _next_weekday(today, SUNDAY)
    if ref == "next_weekend":
        return _next_weekday(today, SATURDAY) + timedelta(days=7)
    return None


def stay_dates(understood: Understanding, today: date) -> tuple[date | None, date | None]:
    start = start_day(understood, today)
    if start is None:
        return None, None
    if understood.check_out and understood.check_out > start:
        return start, understood.check_out
    return start, start + timedelta(days=max(1, understood.nights or 1))


def trip_days(understood: Understanding, today: date) -> tuple[date, date, bool]:
    """Days to show weather for; True when Tripi assumed them (the next 3 days)."""
    start, end = stay_dates(understood, today)
    if start is None or end is None:
        return today, today + timedelta(days=2), True
    return start, end, False


def has_asked_before(request: ChatRequest) -> bool:
    """Ask at most one clarifying question per conversation (TF31, DeepResearch §5.3)."""
    return any(turn.role == "assistant" and turn.kind == "clarify" for turn in request.history)
