"""Weather and packing Skills: numbers from the provider, the list from rules, never the LLM."""

from datetime import UTC, date, datetime
from functools import cache
from pathlib import Path

import yaml

from app.clients.weather import SOURCE, DayWeather, WeatherClient
from app.services.assistant.schemas import Answer, Card, CardLine
from app.services.summary.vi_text import normalize_text

WEEKDAYS = ["T2", "T3", "T4", "T5", "T6", "T7", "CN"]
# Kept out of app/lexicons: that folder's versions feed the summary input hash.
RULES = Path(__file__).parents[1] / "packing.v1.yaml"


@cache
def packing_rules() -> dict:
    return yaml.safe_load(RULES.read_text(encoding="utf-8"))


def _label(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]} {day:%d/%m}"


async def weather(
    client: WeatherClient, place_name: str, start: date, end: date, *, is_assumed: bool
) -> tuple[Answer, list[DayWeather]]:
    place = await client.find_place(place_name)
    if place is None:
        return Answer(
            kind="clarify", text="Bạn ghi rõ tên nơi muốn xem thời tiết giúp Tripi nha."
        ), []
    days = await client.forecast(place, start, end)
    if not days:
        return (
            Answer(
                kind="no_result",
                text="Chưa có dự báo cho ngày đó, gần ngày đi bạn hỏi lại Tripi nha.",
            ),
            [],
        )
    lines = [
        CardLine(
            label=_label(d.day), detail=f"{d.min_c}–{d.max_c}°C, {d.sky}, mưa {d.rain_chance}%"
        )
        for d in days
    ]
    note = " (3 ngày tới)" if is_assumed else ""
    answer = Answer(
        kind="answer",
        text=f"Dự báo thời tiết {place.name}{note} ở thẻ bên dưới nha.",
        cards=[
            Card(
                ref="r1",
                id=f"weather:{place.name}",
                kind="weather",
                title=f"Thời tiết {place.name}",
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
                "place": place.name,
                "assumedDays": is_assumed,
                "days": [
                    {
                        "day": _label(d.day),
                        "minC": d.min_c,
                        "maxC": d.max_c,
                        "rainChance": d.rain_chance,
                        "sky": d.sky,
                    }
                    for d in days
                ],
            }
        ],
        suggestions=["Cần mang gì?", "Tìm chỗ ở"],
    )
    return answer, days


def packing_list(place_and_question: str, days: list[DayWeather], nights: int) -> list[str]:
    rules = packing_rules()
    text = f" {normalize_text(place_and_question)} "
    items = list(rules["base"])
    if any(f" {word} " in text for word in rules["beach"]["match"]):
        items += rules["beach"]["items"]
    if any(d.rain_chance >= rules["rain"]["min_chance"] for d in days):
        items += rules["rain"]["items"]
    if any(d.max_c >= rules["hot"]["min_temp"] for d in days):
        items += rules["hot"]["items"]
    if any(d.min_c <= rules["cool"]["max_temp"] for d in days):
        items += rules["cool"]["items"]
    if nights >= rules["long"]["min_nights"]:
        items += rules["long"]["items"]
    return list(dict.fromkeys(items))


def packing(place_and_question: str, days: list[DayWeather], nights: int) -> Answer:
    items = packing_list(place_and_question, days, nights)
    return Answer(
        kind="answer",
        text="Tripi gợi ý mấy món nên mang theo ở thẻ bên dưới nha.",
        cards=[
            Card(
                ref="r1",
                id="packing",
                kind="checklist",
                title="Nên mang theo",
                price_from=None,
                price_basis="unavailable",
                observed_at=datetime.now(UTC),
                lines=[CardLine(label=item) for item in items],
            )
        ],
        facts=[
            {
                "ref": "r1",
                "kind": "checklist",
                "items": items,
                "basedOnWeather": bool(days),
            }
        ],
    )
