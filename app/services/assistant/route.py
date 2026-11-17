"""Distance and travel time between two points, estimated without a map API (plan B4).

Bảo chose estimates over a paid map provider (16/11): straight-line distance times a road
factor, at an average speed. Good enough to order stops and to say "khoảng 10 phút"; every
leg says it is an estimate. Constants are [HIỆU CHỈNH] (DeepResearch trợ lý đầy đủ §3.2).
"""

from dataclasses import dataclass
from math import asin, cos, radians, sin, sqrt

EARTH_KM = 6371.0
ROAD_FACTOR = 1.3
CITY_KMH = 30
INTERCITY_KMH = 60
INTERCITY_FROM_KM = 40  # longer legs are on highways


@dataclass(frozen=True)
class Leg:
    km: float
    minutes: int
    is_estimate: bool = True


def haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(radians, (*a, *b))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_KM * asin(sqrt(h))


def estimate_leg(a: tuple[float, float], b: tuple[float, float]) -> Leg:
    km = haversine_km(a, b) * ROAD_FACTOR
    speed = INTERCITY_KMH if km >= INTERCITY_FROM_KM else CITY_KMH
    return Leg(km=round(km, 1), minutes=max(1, round(km / speed * 60)))
