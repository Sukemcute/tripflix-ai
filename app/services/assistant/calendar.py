"""Real-time calendar and Vietnamese holidays for the LLM inputs and for date answers (TF31).

The LLM never computes a weekday or a date: it reads them from `build_calendar`. Lunar holidays
are listed by year in holidays.v1.yaml; code never computes the lunar calendar.
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import cache
from pathlib import Path

import yaml

from app.services.assistant.admission import VIETNAM
from app.services.summary.vi_text import normalize_text

HOLIDAYS = Path(__file__).with_name("holidays.v1.yaml")
WEEKDAYS_VI = ["thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật"]
WEEKDAY_SHORT = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
SATURDAY, SUNDAY = 5, 6
CALENDAR_DAYS = 14
HOLIDAY_WINDOW_DAYS = 400
RELATIVE_NAMES = {0: "hôm nay", 1: "mai", 2: "mốt"}


def now_in_vietnam(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)).astimezone(VIETNAM)


def next_weekday(today: date, weekday: int) -> date:
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def weekend_start(today: date, *, is_next: bool) -> date:
    """First day of "cuối tuần này" (today on a Sunday) or of "cuối tuần sau"."""
    if is_next:
        return next_weekday(today, SATURDAY) + timedelta(days=7)
    return today if today.weekday() == SUNDAY else next_weekday(today, SATURDAY)


def weekend_days(start: date) -> list[date]:
    return [start] if start.weekday() == SUNDAY else [start, start + timedelta(days=1)]


@dataclass(frozen=True)
class Holiday:
    id: str
    name: str
    main_day: date
    start: date
    end: date
    is_lunar: bool

    @property
    def year(self) -> int:
        return self.main_day.year


@cache
def _holiday_rows() -> dict:
    return yaml.safe_load(HOLIDAYS.read_text(encoding="utf-8"))


def _span(row: dict, main_day: date, *, is_lunar: bool) -> Holiday:
    return Holiday(
        row["id"],
        row["name"],
        main_day,
        main_day - timedelta(days=row["before"]),
        main_day + timedelta(days=row["after"]),
        is_lunar,
    )


def holidays_between(start: date, end: date) -> list[Holiday]:
    """Holidays that overlap [start, end], earliest first."""
    rows = _holiday_rows()
    found = [
        _span(row, date(year, row["month"], row["day"]), is_lunar=False)
        for row in rows["fixed"]
        for year in range(start.year - 1, end.year + 1)
    ]
    found += [
        _span(row, main_day, is_lunar=True) for row in rows["lunar"] for main_day in row["dates"]
    ]
    return sorted((h for h in found if h.end >= start and h.start <= end), key=lambda h: h.start)


def build_calendar(now: datetime) -> dict:
    today = now.date()
    days = []
    for offset in range(CALENDAR_DAYS):
        day = today + timedelta(days=offset)
        entry = {
            "date": day.isoformat(),
            "label": f"{WEEKDAY_SHORT[day.weekday()]} {day:%d/%m}",
        }
        if offset in RELATIVE_NAMES:
            entry["rel"] = RELATIVE_NAMES[offset]
        days.append(entry)
    next_monday = today + timedelta(days=7 - today.weekday())
    return {
        "now": f"{now:%Y-%m-%d %H:%M}",
        "today": today.isoformat(),
        "weekday": WEEKDAYS_VI[today.weekday()],
        "days": days,
        "thisWeekend": [d.isoformat() for d in weekend_days(weekend_start(today, is_next=False))],
        "nextWeekend": [d.isoformat() for d in weekend_days(weekend_start(today, is_next=True))],
        "nextWeek": [next_monday.isoformat(), (next_monday + timedelta(days=6)).isoformat()],
        "holidays": [
            {
                "name": h.name,
                "from": h.start.isoformat(),
                "to": h.end.isoformat(),
                "isLunar": h.is_lunar,
            }
            for h in holidays_between(today, today + timedelta(days=HOLIDAY_WINDOW_DAYS))
            if h.end >= today
        ],
    }


RESPONDER_KEYS = ("now", "today", "weekday", "thisWeekend", "holidays")


def responder_calendar(calendar: dict) -> dict:
    return {key: calendar[key] for key in RESPONDER_KEYS}


def holiday_cue(folded: str) -> str | None:
    """The id of the holiday a folded message names, or None."""
    rows = _holiday_rows()
    for row in [*rows["fixed"], *rows["lunar"]]:
        if re.search(row["cue"], folded):
            return row["id"]
    return None


def _pick_holiday(holiday_id: str, folded: str, today: date) -> Holiday | None:
    """The occurrence meant: this year's, else the next one; "năm sau" is next calendar year."""
    found = [h for h in holidays_between(today, today + timedelta(days=800)) if h.id == holiday_id]
    wanted = today.year + 1 if re.search(r"\bnam (sau|toi)\b", folded) else today.year
    pick = next((h for h in found if h.year == wanted and h.end >= today), None)
    return pick or next((h for h in found if h.year >= wanted and h.end >= today), None)


def holiday_answer(message: str, today: date) -> str | None:
    """ "Tết năm nay ngày mấy": the dates of that holiday from the list, or None."""
    folded = normalize_text(message)
    holiday_id = holiday_cue(folded)
    pick = _pick_holiday(holiday_id, folded, today) if holiday_id else None
    if pick is None:
        return None
    head = f"{pick.name} {pick.year}"
    if pick.id == "tet":
        head = f"Mùng 1 {head}"
    text = f"{head} vào {WEEKDAYS_VI[pick.main_day.weekday()]}, {pick.main_day:%d/%m/%Y}."
    if pick.start != pick.end:
        text += (
            f" Kỳ nghỉ thường tính từ {WEEKDAYS_VI[pick.start.weekday()]} {pick.start:%d/%m} "
            f"đến {WEEKDAYS_VI[pick.end.weekday()]} {pick.end:%d/%m}; "
            "ngày nghỉ chính thức do Nhà nước công bố."
        )
    return text


NEXT_WEEK_CUES = [
    r"(t2|thu (2|hai))", r"(t3|thu (3|ba))", r"(t4|thu (4|tu))", r"(t5|thu (5|nam))",
    r"(t6|thu (6|sau))", r"(t7|thu (7|bay))", r"(chu nhat|cn)",
]  # fmt: skip
HOLIDAY_WORD = r"\b(dip|nghi|le|tet|gio to|quoc khanh)\b"


def relative_dates(message: str, today: date) -> tuple[date, date | None] | None:
    """Days a message names that day_ref cannot say: "3 ngày nữa", "thứ 6 tuần sau", "dịp Tết".

    The LLM reads these from the calendar too, but it often skips them; code is the backup.
    """
    folded = normalize_text(message)
    next_monday = today + timedelta(days=7 - today.weekday())
    if found := re.search(r"\b(\d{1,3}) ngay nua\b", folded):
        return today + timedelta(days=int(found.group(1))), None
    if re.search(r"\bdau tuan (sau|toi)\b", folded):
        return next_monday, None
    for offset, cue in enumerate(NEXT_WEEK_CUES):
        if re.search(rf"\b{cue} tuan (sau|toi)\b", folded):
            return next_monday + timedelta(days=offset), None
    holiday_id = holiday_cue(folded) if re.search(HOLIDAY_WORD, folded) else None
    pick = _pick_holiday(holiday_id, folded, today) if holiday_id else None
    if pick is not None:
        return pick.start, pick.end if pick.end > pick.start else None
    return None
