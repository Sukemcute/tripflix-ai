"""Weather and packing Skills: numbers from the provider, the list from rules, never the LLM.

v3.1 (Expo Web report §7.3): both use the same days (the trip's or the asked ones), the
packing list carries a reason per item, and what the user already has, wants only, or does
not do (no beach) shapes the one list that both the card and the Responder see.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import cache
from pathlib import Path
from typing import Literal

import yaml

from app.clients.weather import SOURCE, DayWeather, WeatherClient
from app.services.assistant.planner import DayWindow
from app.services.assistant.schemas import Answer, Card, CardLine, Understanding
from app.services.summary.vi_text import normalize_text

WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
# Kept out of app/lexicons: that folder's versions feed the summary input hash.
RULES = Path(__file__).parents[1] / "packing.v2.yaml"
WeatherStatus = Literal["ok", "none", "past", "unknown_place", "failed", "no_place"]


@cache
def packing_rules() -> dict:
    return yaml.safe_load(RULES.read_text(encoding="utf-8"))


def day_label(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day:%d/%m}"


@dataclass
class Forecast:
    status: WeatherStatus
    place: str = ""
    days: list[DayWeather] | None = None


async def forecast(client: WeatherClient, place_name: str, window: DayWindow) -> Forecast:
    if window.is_past:
        return Forecast("past")
    place = await client.find_place(place_name)
    if place is None:
        return Forecast("unknown_place")
    days = await client.forecast(place, window.start, window.end)
    return Forecast("ok" if days else "none", place.name, days)


def weather_answer(found: Forecast, place_name: str, window: DayWindow) -> Answer:
    if found.status == "past":
        return Answer(
            kind="no_result",
            text="Tripi chưa có dữ liệu thời tiết những ngày đã qua, chỉ có dự báo tới "
            "16 ngày tới thôi nha.",
        )
    if found.status == "unknown_place":
        return Answer(
            kind="no_result",
            text=f"Tripi chưa tìm được nơi «{place_name[:60]}» ở Việt Nam để xem dự báo.",
        )
    if found.status != "ok" or not found.days:
        when = f"{window.start:%d/%m}" + (
            f"–{window.end:%d/%m}" if window.end != window.start else ""
        )
        return Answer(
            kind="no_result",
            text=f"Chưa có dự báo cho {when}, gần ngày đi bạn hỏi lại Tripi nha.",
        )
    days = found.days
    lines = [
        CardLine(
            label=day_label(d.day), detail=f"{d.min_c}–{d.max_c}°C, {d.sky}, mưa {d.rain_chance}%"
        )
        for d in days
    ]
    first = days[0]
    # The lead states the asked day itself, so the number and its day always travel together.
    lead = (
        f"{found.place} {day_label(first.day)}: {first.min_c}–{first.max_c}°C, {first.sky}, "
        f"khả năng mưa {first.rain_chance}%."
        if len(days) == 1
        else None
    )
    note = " (3 ngày tới)" if window.is_assumed else ""
    return Answer(
        kind="answer",
        text=lead or f"Dự báo thời tiết {found.place}{note} ở thẻ bên dưới nha.",
        lead=lead,
        cards=[
            Card(
                ref="r1",
                id=f"weather:{found.place}",
                kind="weather",
                title=f"Thời tiết {found.place}",
                price_from=None,
                price_basis="unavailable",
                observed_at=datetime.now(UTC),
                lines=lines,
                source=SOURCE,
            )
        ],
        facts=[
            {
                "ref": "r1",
                "kind": "weather",
                "place": found.place,
                "assumedDays": window.is_assumed,
                "days": [_day_fact(d) for d in days],
            }
        ],
        suggestions=["Cần mang gì?", "Tìm chỗ ở"],
    )


def _day_fact(d: DayWeather) -> dict:
    return {
        "day": day_label(d.day),
        "minC": d.min_c,
        "maxC": d.max_c,
        "rainChance": d.rain_chance,
        "sky": d.sky,
    }


def _is_rainy(day: DayWeather, rules: dict) -> bool:
    rain = rules["groups"]["rain"]
    return day.rain_chance >= rain["min_chance"] or normalize_text(day.sky) in rain["skies"]


def _reasons(days: list[DayWeather], rules: dict) -> dict[str, str]:
    groups = rules["groups"]
    reasons: dict[str, str] = {}
    rainy = [d for d in days if _is_rainy(d, rules)]
    if rainy:
        worst = max(rainy, key=lambda d: d.rain_chance)
        reasons["rain"] = f"{worst.sky}, mưa {worst.rain_chance}% {day_label(worst.day)}"
    hot = [d for d in days if d.max_c >= groups["hot"]["min_temp"]]
    if hot:
        top = max(hot, key=lambda d: d.max_c)
        reasons["hot"] = f"nóng tới {top.max_c}°C {day_label(top.day)}"
    cool = [d for d in days if d.min_c <= groups["cool"]["max_temp"]]
    if cool:
        low = min(cool, key=lambda d: d.min_c)
        reasons["cool"] = f"lạnh {low.min_c}°C {day_label(low.day)}"
    return reasons


def _wanted_groups(only: list[str], rules: dict) -> set[str] | None:
    if not only:
        return None
    wanted = set()
    for phrase in only:
        folded = f" {normalize_text(phrase)} "
        for name, group in rules["groups"].items():
            if any(f" {alias} " in folded for alias in group.get("aliases", [])):
                wanted.add(name)
    return wanted or None


def _already_have(item: str, have: list[str]) -> bool:
    folded = f" {normalize_text(item)} "
    for phrase in have:
        words = [w for w in normalize_text(phrase).split() if len(w) > 1 or w == "o"]
        if words and all(f" {w} " in folded for w in words):
            return True
    return False


def packing_list(
    understood: Understanding, place: str, days: list[DayWeather], nights: int
) -> list[tuple[str, str]]:
    """(item, reason) pairs; the same list feeds the card and the Responder (K06–K09)."""
    rules = packing_rules()
    groups = rules["groups"]
    text = f" {normalize_text(place + ' ' + understood.query)} "
    reasons = _reasons(days, rules)
    is_beach = understood.is_beach_trip
    if is_beach is None:
        is_beach = any(f" {word} " in text for word in groups["beach"]["match"])
    chosen: list[tuple[str, str, str]] = [(i, "", "base") for i in groups["base"]["items"]]
    if is_beach:
        chosen += [(i, "đi biển", "beach") for i in groups["beach"]["items"]]
    for name in ("rain", "hot", "cool"):
        if name in reasons:
            chosen += [(i, reasons[name], name) for i in groups[name]["items"]]
    if nights >= groups["long"]["min_nights"]:
        chosen += [(i, f"{nights} đêm", "long") for i in groups["long"]["items"]]
    wanted = _wanted_groups(understood.packing_only, rules)
    items = [
        (item, reason)
        for item, reason, group in chosen
        if (wanted is None or group in wanted) and not _already_have(item, understood.packing_have)
    ]
    items = list(dict.fromkeys(items))
    return items[: understood.packing_limit] if understood.packing_limit else items


NOTES = {
    "ok": "",
    "past": "",
    "failed": " Tripi chưa kiểm được thời tiết lúc này nên đây là danh sách cơ bản.",
    "none": " Chưa có dự báo cho ngày đi nên đây là danh sách cơ bản.",
    "unknown_place": " Tripi chưa xem được dự báo nơi này nên đây là danh sách cơ bản.",
    "no_place": " Bạn cho Tripi biết nơi đến để gợi ý theo thời tiết nha.",
}


def packing(understood: Understanding, place: str, found: Forecast, nights: int) -> Answer:
    days = found.days or []
    items = packing_list(understood, place, days, nights)
    # Say plainly when the list is not based on a forecast (Expo Web report T15, T16, Q3).
    note = NOTES[found.status]
    if not items:
        return Answer(kind="answer", text="Bạn đã có đủ những món Tripi định gợi ý rồi nè." + note)
    return Answer(
        kind="answer",
        text="Tripi gợi ý mấy món nên mang theo ở thẻ bên dưới nha." + note,
        cards=[
            Card(
                ref="r1",
                id="packing",
                kind="checklist",
                title="Nên mang theo",
                price_from=None,
                price_basis="unavailable",
                observed_at=datetime.now(UTC),
                lines=[CardLine(label=item, detail=reason) for item, reason in items],
            )
        ],
        facts=[
            {
                "ref": "r1",
                "kind": "checklist",
                "place": found.place or place,
                "items": [{"item": item, "why": reason} for item, reason in items],
                "weather": found.status,
                "days": [_day_fact(d) for d in days],
                "userHas": understood.packing_have,
            }
        ],
    )
