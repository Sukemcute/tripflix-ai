"""Weather for Tripi (Bảo, 2026-11-16: the free Open-Meteo API, no key).

Open-Meteo's free tier is for non-commercial use, data under CC BY 4.0: the app must show
"Open-Meteo.com" next to it. Checked live 2026-11-16: geocoding with countryCode=VN found
"Vũng Tàu"; the daily forecast covers 16 days.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, TypeVar

import httpx

T = TypeVar("T")
SOURCE = "Open-Meteo.com"
FORECAST_DAYS = 16
CACHE_SECONDS = 30 * 60
# WMO weather codes grouped into words the Responder may repeat.
_SKY = [
    ((0,), "trời quang"),
    ((1, 2, 3), "có mây"),
    ((45, 48), "sương mù"),
    ((51, 53, 55, 56, 57), "mưa phùn"),
    ((61, 63, 65, 66, 67), "có mưa"),
    ((80, 81, 82), "mưa rào"),
    ((95, 96, 99), "có dông"),
]


@dataclass(frozen=True)
class Place:
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class DayWeather:
    day: date
    min_c: int
    max_c: int
    rain_chance: int  # %, max of the day
    sky: str


class WeatherClient(Protocol):
    async def find_place(self, name: str) -> Place | None: ...
    async def forecast(self, place: Place, start: date, end: date) -> list[DayWeather]: ...


def describe_sky(code: int) -> str:
    return next((label for codes, label in _SKY if code in codes), "có mây")


class OpenMeteoWeather:
    def __init__(self, http: httpx.AsyncClient | None = None, clock=time.monotonic) -> None:
        self.http = http or httpx.AsyncClient(timeout=3)
        self.clock = clock
        # shortcut: per-process cache, enough for one ai-service; move to the shared store
        # when several replicas run.
        self.cache: dict[str, tuple[float, Any]] = {}

    async def find_place(self, name: str) -> Place | None:
        def parse(data: dict) -> Place | None:
            results = data.get("results") or []
            if not results:
                return None
            first = results[0]
            return Place(first["name"], float(first["latitude"]), float(first["longitude"]))

        return await self._get(
            "https://geocoding-api.open-meteo.com/v1/search",
            {"name": name, "count": 1, "language": "vi", "countryCode": "VN", "format": "json"},
            parse,
        )

    async def forecast(self, place: Place, start: date, end: date) -> list[DayWeather]:
        def parse(data: dict) -> list[DayWeather]:
            daily = data["daily"]
            return [
                DayWeather(
                    date.fromisoformat(day),
                    round(daily["temperature_2m_min"][i]),
                    round(daily["temperature_2m_max"][i]),
                    int(daily["precipitation_probability_max"][i] or 0),
                    describe_sky(int(daily["weather_code"][i])),
                )
                for i, day in enumerate(daily["time"])
            ]

        days = await self._get(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": round(place.latitude, 3),
                "longitude": round(place.longitude, 3),
                "daily": "temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,weather_code",
                "timezone": "Asia/Ho_Chi_Minh",
                "forecast_days": FORECAST_DAYS,
            },
            parse,
        )
        return [d for d in days if start <= d.day <= end]

    async def _get(self, url: str, params: dict, parse: Callable[[dict], T]) -> T:
        key = f"{url}?{sorted(params.items())}"
        hit = self.cache.get(key)
        if hit and hit[0] > self.clock():
            return hit[1]
        response = await self.http.get(url, params=params)
        response.raise_for_status()
        value = parse(response.json())
        self.cache[key] = (self.clock() + CACHE_SECONDS, value)
        return value
