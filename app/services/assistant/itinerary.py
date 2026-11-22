"""Itinerary Engine (plan B5): code picks and orders the stops, the LLM only says them.

LLMs alone plan trips badly (TravelPlanner 0.6%); ItiNera picks with scores and orders by
spatial clustering plus a small TSP, then lets the LLM write (DeepResearch trợ lý đầy đủ §4).
No network here: candidates, base point and weather come in, a checked plan comes out.
Every constant is [HIỆU CHỈNH].
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import permutations
from math import atan2
from typing import Literal

from app.clients.places import PointOfInterest
from app.services.assistant.route import Leg, estimate_leg

Pace = Literal["relaxed", "packed"]
SIGHTS_PER_DAY = {"relaxed": 3, "packed": 4}
HALF_DAY_SIGHTS = 2
MAX_STOPS_TO_PERMUTE = 6
MAX_KM_PER_DAY = 40.0
RAINY = 60  # % rain chance that moves indoor stops first
INTEREST_BONUS = 0.5
SIGHT_KINDS = {"see"}
MEAL_KINDS = {"food", "cafe"}
INDOOR_TAGS = {"indoor", "museum", "mall", "cafe", "market"}
MORNING_TAGS = {"beach", "hike"}
EVENING_TAGS = {"sunset", "night_market", "nightlife"}


@dataclass(frozen=True)
class Stop:
    place: PointOfInterest
    slot: Literal["sáng", "trưa", "chiều", "tối"]
    leg: Leg  # from the stop before (the stay for the first one)


@dataclass(frozen=True)
class ItineraryDay:
    index: int  # 1-based
    day: date | None
    stops: tuple[Stop, ...]
    km: float  # stay → stops → stay
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Itinerary:
    days: tuple[ItineraryDay, ...]
    assumptions: tuple[str, ...] = field(default=())

    @property
    def total_km(self) -> float:
        return round(sum(d.km for d in self.days), 1)


def _point(place: PointOfInterest) -> tuple[float, float]:
    return (place.latitude, place.longitude)


def _score(place: PointOfInterest, interests: Sequence[str]) -> float:
    hits = sum(1 for tag in place.tags if tag in interests)
    return (place.popularity or 0.1) * (1 + INTEREST_BONUS * hits)


def _loop_km(base: tuple[float, float], stops: Sequence[PointOfInterest]) -> float:
    points = [base, *(_point(s) for s in stops), base]
    return sum(estimate_leg(a, b).km for a, b in zip(points, points[1:], strict=False))


def _shortest_order(
    base: tuple[float, float], stops: Sequence[PointOfInterest]
) -> list[PointOfInterest]:
    """Every order for a handful of stops (≤ 720): small enough to be exact."""
    if len(stops) > MAX_STOPS_TO_PERMUTE:
        stops = stops[:MAX_STOPS_TO_PERMUTE]
    return list(min(permutations(stops), key=lambda order: _loop_km(base, order), default=()))


def _by_time_of_day(stops: list[PointOfInterest], *, is_rainy: bool) -> list[PointOfInterest]:
    """Rules on top of the shortest loop: beach early, sunset last; indoor first when it rains."""

    def rank(place: PointOfInterest) -> int:
        tags = set(place.tags)
        if is_rainy and tags & INDOOR_TAGS:
            return 0
        if tags & EVENING_TAGS:
            return 3
        if tags & MORNING_TAGS:
            return 1
        return 2

    return sorted(stops, key=rank)  # stable: keeps the shortest order inside each rank


Slot = Literal["sáng", "trưa", "chiều", "tối"]


def travel_slots(*, arrival: str | None = None, departure: str | None = None) -> set[Slot]:
    """Conservative half-day windows; leave two hours before the return flight."""
    allowed: set[Slot] = {"sáng", "trưa", "chiều", "tối"}
    if arrival:
        if arrival >= "17:00":
            allowed &= {"tối"}
        elif arrival >= "12:00":
            allowed &= {"chiều", "tối"}
    if departure:
        hours = {"sáng": 8, "trưa": 12, "chiều": 14, "tối": 18}
        hour, minute = map(int, departure.split(":"))
        allowed = {slot for slot in allowed if hours[slot] * 60 + 120 <= hour * 60 + minute}
    return allowed


def _slots(count: int) -> list[Slot]:
    morning = max(1, count // 2) if count else 0
    slots: list[Slot] = []
    for position in range(count):
        slots.append("sáng" if position < morning else "chiều")
    return slots


def _day(
    index: int,
    day: date | None,
    base: tuple[float, float],
    sights: list[PointOfInterest],
    meal: PointOfInterest | None,
    notes: list[str],
) -> ItineraryDay:
    slots = _slots(len(sights))
    if sights and set(sights[-1].tags) & EVENING_TAGS:
        slots[-1] = "chiều"  # sunset at the end of the afternoon
    stops: list[Stop] = []
    previous = base
    for place, slot in zip(sights, slots, strict=True):
        stops.append(Stop(place, slot, estimate_leg(previous, _point(place))))
        previous = _point(place)
    if meal is not None:
        stops.append(Stop(meal, "tối", estimate_leg(previous, _point(meal))))
        previous = _point(meal)
    km = sum(s.leg.km for s in stops) + (estimate_leg(previous, base).km if stops else 0)
    return ItineraryDay(index, day, tuple(stops), round(km, 1), tuple(notes))


def build_itinerary(
    candidates: Sequence[PointOfInterest],
    *,
    base: tuple[float, float],
    days: int,
    start: date | None = None,
    interests: Sequence[str] = (),
    pace: Pace = "relaxed",
    rain_by_day: Sequence[int | None] = (),
    half_days: Sequence[int] = (),
) -> Itinerary:
    """A plan of `days` days around `base` (the stay, or the town centre when none is chosen).

    half_days: 1-based days that are half lost to the trip there or back.
    """
    unique = {p.id: p for p in candidates}.values()
    sights = sorted(
        (p for p in unique if p.kind in SIGHT_KINDS), key=lambda p: -_score(p, interests)
    )
    meals = [p for p in unique if p.kind in MEAL_KINDS]
    wanted = [
        HALF_DAY_SIGHTS if i in half_days else SIGHTS_PER_DAY[pace] for i in range(1, days + 1)
    ]
    chosen = sights[: sum(wanted)]
    # Sweep: sort by direction from the stay so each day heads one way.
    chosen.sort(key=lambda p: atan2(p.latitude - base[0], p.longitude - base[1]))
    plan_days: list[ItineraryDay] = []
    used_meals: set[str] = set()
    position = 0
    for index, count in enumerate(wanted, 1):
        group = chosen[position : position + count]
        position += count
        rain = rain_by_day[index - 1] if index - 1 < len(rain_by_day) else None
        is_rainy = rain is not None and rain > RAINY
        ordered = _by_time_of_day(_shortest_order(base, group), is_rainy=is_rainy)
        # Too far for one day: drop the lowest-scored stop and order again.
        while len(ordered) > 1 and _loop_km(base, ordered) > MAX_KM_PER_DAY:
            ordered.remove(min(ordered, key=lambda p: _score(p, interests)))
            ordered = _by_time_of_day(_shortest_order(base, ordered), is_rainy=is_rainy)
        last = _point(ordered[-1]) if ordered else base
        meal = min(
            (m for m in meals if m.id not in used_meals),
            key=lambda m: estimate_leg(last, _point(m)).km,
            default=None,
        )
        if meal is not None:
            used_meals.add(meal.id)
        notes = (
            [f"Có thể mưa ({rain}%): điểm trong nhà xếp trước, nhớ mang áo mưa."]
            if is_rainy
            else []
        )
        day = start + timedelta(days=index - 1) if start else None
        plan_days.append(_day(index, day, base, ordered, meal, notes))
    assumptions = ["Quãng đường và thời gian là ước tính, chưa tính kẹt xe."]
    if not sights:
        assumptions.append("Chưa có điểm tham quan có tọa độ cho nơi này.")
    return Itinerary(tuple(plan_days), tuple(assumptions))


MEALS: tuple[tuple[Slot, str], ...] = (("sáng", "ăn sáng"), ("trưa", "ăn trưa"), ("tối", "ăn tối"))


def build_meal_plan(
    candidates: Sequence[PointOfInterest],
    *,
    base: tuple[float, float],
    days: int,
    start: date | None = None,
) -> Itinerary:
    """A food-only plan (Vũng Tàu report P1): breakfast, lunch, dinner a day, each the
    closest place not used yet, so the day stays short. Missing meals are said, not invented.
    """
    unique = list({p.id: p for p in candidates if p.kind in MEAL_KINDS}.values())
    unique.sort(key=lambda p: -p.popularity)  # ties on distance go to the better known place
    used: set[str] = set()
    plan_days: list[ItineraryDay] = []
    for index in range(1, days + 1):
        stops: list[Stop] = []
        missing: list[str] = []
        previous = base
        for slot, label in MEALS:
            place = min(
                (p for p in unique if p.id not in used),
                key=lambda p: estimate_leg(previous, _point(p)).km,
                default=None,
            )
            if place is None:
                missing.append(label)
                continue
            used.add(place.id)
            stops.append(Stop(place, slot, estimate_leg(previous, _point(place))))
            previous = _point(place)
        km = sum(s.leg.km for s in stops) + (estimate_leg(previous, base).km if stops else 0)
        notes = (f"Chưa đủ quán cho bữa {', '.join(missing)}.",) if missing and stops else ()
        day = start + timedelta(days=index - 1) if start else None
        plan_days.append(ItineraryDay(index, day, tuple(stops), round(km, 1), notes))
    assumptions = ["Chỉ gồm quán ăn, cà phê theo bữa; quãng đường là ước tính."]
    return Itinerary(tuple(plan_days), tuple(assumptions))


def follow_reel(
    stops_by_day: Sequence[Sequence[PointOfInterest]], *, base: tuple[float, float]
) -> Itinerary:
    """ "Đi y chang" a reel: keep the author's order, only add the legs."""
    days = tuple(
        _day(index, None, base, list(places), None, [])
        for index, places in enumerate(stops_by_day, 1)
    )
    return Itinerary(days, ("Giữ đúng thứ tự của người đăng reel.",))
