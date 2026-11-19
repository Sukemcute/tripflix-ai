"""Stage B Skills (plan B6, B7): plan a whole trip, then edit it by small operations.

Code decides every name, distance and option; the Responder only says them. Edits are
operations on the trip memory the app keeps (DeepResearch trợ lý đầy đủ §5): pick a stay,
drop a stop, undo. Coordinates of the user never go anywhere: the origin is a city name.
"""

import asyncio
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import httpx

from app.clients.places import ATTRIBUTION, PlacesClient, PointOfInterest
from app.clients.weather import WeatherClient
from app.services.assistant import planner
from app.services.assistant.itinerary import Slot, build_itinerary, build_meal_plan, travel_slots
from app.services.assistant.route import estimate_leg
from app.services.assistant.schemas import (
    Answer,
    Awaiting,
    Card,
    CardAction,
    CardLine,
    DraftChoice,
    DraftOp,
    DraftStop,
    DraftTransport,
    Flights,
    TripContext,
    Understanding,
)
from app.services.assistant.skills import weather as weather_skill
from app.services.assistant.skills.flight import (
    draft_flights,
    find_airport,
    flight_title,
    search_flights,
)
from app.services.assistant.skills.stay import search_stays, vnd
from app.services.assistant.skills.trip import hotel_room
from app.services.assistant.transport import attribution, bus_routes
from app.services.summary.vi_text import normalize_text

# The forecast only reorders stops for rain: a slow one is skipped, not waited for.
RAIN_SECONDS = 2.5
DEFAULT_DAYS = 2  # "đi Vũng Tàu" alone: plan 2 days and say so [HIỆU CHỈNH]
MAX_DAYS = 7
TRIPFLIX_OPTIONS = 3
EXTERNAL_OPTIONS = 1
COORD_DIGITS = 5  # about 1 m; keeps the trip memory small
logger = logging.getLogger(__name__)
REVIEW_CHIPS = ["Chốt và đặt", "Đổi chỗ ở", "Đổi chuyến bay"]
REVIEW_QUESTION = "Bạn muốn đổi chuyến bay hay chỗ ở không, hay chốt luôn?"
STAY_SECONDS = 3.0
INTEREST_TAGS = {
    "beach", "viewpoint", "sunset", "museum", "park", "market", "temple", "nightlife", "hike",
}  # fmt: skip


def _round(value: float) -> float:
    return round(value, COORD_DIGITS)


def _stop(place: PointOfInterest, slot: Slot) -> DraftStop:
    return DraftStop(
        id=place.id,
        name=place.name[:120],
        lat=_round(place.latitude),
        lng=_round(place.longitude),
        slot=slot,
    )


def _point(stop: DraftStop) -> tuple[float, float]:
    return (stop.lat, stop.lng)


@dataclass
class TripPlanner:
    """One turn of Stage B. Reads Core and the providers; leaves the new memory in `trip`."""

    core: httpx.AsyncClient
    places: PlacesClient
    weather: WeatherClient
    today: date
    trip: TripContext
    notes: list[str] = field(default_factory=list)

    # ---- where the day starts: the chosen stay, else the town centre

    async def _base(self) -> tuple[tuple[float, float], str] | None:
        stay = self.trip.stay
        if stay and stay.lat is not None and stay.lng is not None:
            return (stay.lat, stay.lng), stay.name
        try:
            async with asyncio.timeout(RAIN_SECONDS):
                centre = await self.weather.find_place(self.trip.place)
        except (TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.warning("chat base degraded during plan", exc_info=True)
            return None
        if centre is None:
            return None
        return (centre.latitude, centre.longitude), f"trung tâm {self.trip.place}"

    async def _rain_capped(self, days: int) -> list[int | None]:
        try:
            async with asyncio.timeout(RAIN_SECONDS):
                return await self._rain_by_day(days)
        except (TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.warning("chat weather degraded during plan", exc_info=True)
            return []

    async def _rain_by_day(self, days: int) -> list[int | None]:
        start = self.trip.date_from
        if start is None or start < self.today:
            return []
        window = planner.DayWindow(start, start + timedelta(days=days - 1), False, False)
        found = await weather_skill.forecast(self.weather, self.trip.place, window)
        by_day = {d.day: d.rain_chance for d in found.days or []}
        return [by_day.get(start + timedelta(days=i)) for i in range(days)]

    # ---- the plan

    async def plan(self, understood: Understanding, *, message: str = "") -> Answer:
        place = understood.place or self.trip.place
        if not place:
            return Answer(kind="clarify", text="Bạn muốn đi đâu nè? Mình xếp lộ trình luôn cho.")
        if place != self.trip.place:
            self.trip = TripContext(origin_city=self.trip.origin_city, place=place)
        if understood.from_city:
            # "Lên lịch Vũng Tàu, xuất phát từ TP.HCM": keep the origin for the way there (P2).
            self.trip.origin_city = understood.from_city
        if understood.meals_only:
            self.trip.meals_only = True
        elif understood.interests or understood.pace:
            self.trip.meals_only = False  # a new kind of plan was asked for
        if understood.interests:
            self.trip.interests = [t for t in understood.interests if t in INTEREST_TAGS][:5]
        self.trip.ops = []  # a new plan: nothing to undo
        window = planner.stay_range(understood, self.today)
        if isinstance(window, planner.DateProblem):
            return Answer(kind="clarify", text=window.question)
        if window:
            self.trip.date_from, self.trip.date_to = window
        days = self._days(understood)
        self.trip.adults = understood.adults
        bare = bool(re.search(planner.PLAN_FIRST_CUE, normalize_text(message or understood.query)))
        if not bare and (not self.trip.origin_city or self.trip.date_from is None):
            missing = (
                "origin_dates"
                if not self.trip.origin_city and self.trip.date_from is None
                else "origin"
                if not self.trip.origin_city
                else "dates"
            )
            self.trip.awaiting = Awaiting(intent="plan_trip", missing=missing, nights=days - 1)
            questions = {
                "origin_dates": "Bạn đi từ đâu và đi ngày nào để Tripi xếp lịch "
                "kèm vé máy bay và phòng nha?",
                "origin": "Bạn đi từ đâu để Tripi xếp lịch kèm vé máy bay và phòng nha?",
                "dates": "Bạn đi ngày nào để Tripi xếp lịch kèm vé máy bay và phòng nha?",
            }
            return Answer(
                kind="clarify",
                text=questions[missing],
                suggestions=["Từ TP.HCM", "Từ Hà Nội"] if missing != "dates" else [],
            )
        if bare:
            return await self._build(days, pace=understood.pace or "relaxed")
        self.trip.stay, self.trip.transport, self.trip.return_transport = None, None, None
        self.trip.pending, self.trip.pending_flights = [], []
        kinds = ["food", "cafe"] if self.trip.meals_only else ["see", "food", "cafe"]
        candidates, rain, _, outbound, inbound = await asyncio.gather(
            self._plan_points(kinds),
            self._rain_capped(days),
            self._plan_stays(understood),
            self._plan_flight(understood, returning=False),
            self._plan_flight(understood, returning=True),
        )
        self.trip.transport, self.trip.return_transport = outbound, inbound
        if outbound is None:
            routes = bus_routes(self.trip.origin_city, self.trip.place)
            if routes:
                self.trip.transport = DraftTransport(
                    mode="bus",
                    summary=(
                        f"Xe khách {routes[0].from_station} → {routes[0].to_station}"
                        " · tham khảo, chưa đặt được"
                    )[:160],
                )
        return await self._build(
            days, pace=understood.pace or "relaxed", resources=(candidates, rain)
        )

    async def _plan_points(self, kinds: list[str]) -> list[PointOfInterest]:
        try:
            async with asyncio.timeout(STAY_SECONDS):
                return await self.places.search(city=self.trip.place, kinds=kinds, limit=60)
        except (TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.warning("chat places degraded during plan", exc_info=True)
            return []

    async def _plan_flight(
        self, understood: Understanding, *, returning: bool
    ) -> DraftTransport | None:
        try:
            async with asyncio.timeout(STAY_SECONDS):
                found = await search_flights(
                    self.core,
                    understood.model_copy(
                        update={
                            "intent": "find_flight",
                            "from_airport": None,
                            "to_airport": None,
                            "from_city": self.trip.place if returning else self.trip.origin_city,
                            "to_city": self.trip.origin_city if returning else self.trip.place,
                            "flight_date": self.trip.date_to if returning else self.trip.date_from,
                            "adults": self.trip.adults,
                            "cheapest_only": False,
                            "depart_after": None,
                            "depart_before": None,
                        }
                    ),
                    latest=returning,
                    daytime=not returning,
                )
                options = draft_flights(found.cards)
                return next(
                    (f.model_copy(update={"ref": ""}) for f in options if f.fare_code), None
                )
        except (TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.warning(
                "chat flight degraded during plan (%s)",
                "return" if returning else "outbound",
                exc_info=True,
            )
            return None

    async def _plan_stays(self, understood: Understanding) -> Answer | None:
        if self.trip.date_from is None or self.trip.date_to is None:
            return None
        try:
            async with asyncio.timeout(STAY_SECONDS):
                found = await self.stay_options(understood, tripflix_only=True)
                if self.trip.pending:
                    choice = self.trip.pending[0]
                    response = await self.core.get(f"/api/hotels/{choice.id}")
                    response.raise_for_status()
                    location = response.json().get("location") or {}
                    self.trip.stay = choice.model_copy(
                        update={"ref": "", "lat": location.get("lat"), "lng": location.get("lng")}
                    )
                return found
        except (TimeoutError, httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.warning("chat skill stay degraded during plan", exc_info=True)
            return None

    def _days(self, understood: Understanding) -> int:
        if understood.nights is not None:
            return max(1, min(MAX_DAYS, understood.nights + 1))
        if self.trip.date_from and self.trip.date_to:
            return max(1, min(MAX_DAYS, (self.trip.date_to - self.trip.date_from).days + 1))
        if self.trip.days:
            return len(self.trip.days)
        self.notes.append(f"Tripi tạm xếp {DEFAULT_DAYS} ngày, bạn muốn đi mấy ngày cứ nói nha.")
        return DEFAULT_DAYS

    async def _build(
        self,
        days: int,
        *,
        pace: str = "relaxed",
        resources: tuple[list[PointOfInterest], list[int | None]] | None = None,
    ) -> Answer:
        base = await self._base()
        if base is None and resources and resources[0]:
            first = resources[0][0]
            base = ((first.latitude, first.longitude), first.name)
        if base is None:
            return Answer(kind="no_result", text=f"Tripi chưa định vị được {self.trip.place}.")
        point, base_name = base
        kinds = ["food", "cafe"] if self.trip.meals_only else ["see", "food", "cafe"]
        # Points and forecast at once: both waited in turn took the plan step past its deadline.
        candidates, rain = (
            resources
            if resources is not None
            else await asyncio.gather(
                self.places.search(city=self.trip.place, kinds=kinds, limit=60),
                self._rain_capped(days),
            )
        )
        if self.trip.meals_only:
            plan = build_meal_plan(candidates, base=point, days=days, start=self.trip.date_from)
        else:
            plan = build_itinerary(
                candidates,
                base=point,
                days=days,
                start=self.trip.date_from,
                interests=self.trip.interests,
                pace="packed" if pace == "packed" else "relaxed",
                rain_by_day=rain,
            )
        if not any(day.stops for day in plan.days):
            self.trip.days = []
            return Answer(
                kind="no_result",
                text=f"Tripflix chưa có điểm tham quan có tọa độ ở {self.trip.place} để xếp "
                "lộ trình. Bạn xem các reel về nơi này nha.",
                suggestions=[f"Reel {self.trip.place}"],
            )
        self.trip.days = [[_stop(s.place, s.slot) for s in day.stops] for day in plan.days]
        outbound, inbound = self.trip.transport, self.trip.return_transport
        for index, stops in enumerate(self.trip.days):
            allowed = travel_slots(
                arrival=outbound.arrive_time if index == 0 and outbound else None,
                departure=inbound.depart_time if index == days - 1 and inbound else None,
            )
            self.trip.days[index] = [stop for stop in stops if stop.slot in allowed]
        self.notes += [note for day in plan.days for note in day.notes]
        return self._itinerary_answer(point, base_name, plan.assumptions)

    def _itinerary_answer(
        self, base: tuple[float, float], base_name: str, assumptions: Sequence[str]
    ) -> Answer:
        lines, days_facts = [], []
        for index, stops in enumerate(self.trip.days, 1):
            previous, facts = base, []
            if index == 1:
                outbound = self.trip.transport
                if outbound and outbound.mode == "flight":
                    lines.append(self._flight_line(outbound, index))
                elif outbound:
                    lines.append(CardLine(label=f"Ngày 1 · {outbound.summary}"))
                if self.trip.stay:
                    lines.append(
                        CardLine(
                            label=f"Ngày 1 · Nhận phòng {self.trip.stay.name}",
                            detail=f"{self.trip.date_from:%d/%m}" if self.trip.date_from else "",
                            service="stay",
                        )
                    )
            for stop in stops:
                leg = estimate_leg(previous, _point(stop))
                previous = _point(stop)
                lines.append(
                    CardLine(
                        label=f"Ngày {index} · {stop.slot}",
                        detail=f"{stop.name} · khoảng {leg.km:g} km, {leg.minutes} phút",
                        ref=None,
                    )
                )
                facts.append(
                    {"name": stop.name, "slot": stop.slot, "km": leg.km, "minutes": leg.minutes}
                )
            days_facts.append({"day": index, "stops": facts})
            if index == len(self.trip.days):
                if self.trip.stay:
                    lines.append(
                        CardLine(
                            label=f"Ngày {index} · Trả phòng {self.trip.stay.name}",
                            detail=f"{self.trip.date_to:%d/%m}" if self.trip.date_to else "",
                            service="stay",
                        )
                    )
                if self.trip.return_transport:
                    lines.append(self._flight_line(self.trip.return_transport, index))
        days = len(self.trip.days)
        lead = f"Lộ trình {self.trip.place} {days} ngày đây nè, xếp từ {base_name}."
        chips = ["Đổi chuyến bay", "Đổi chỗ ở", "Thời tiết những ngày đó"]
        if not self.trip.origin_city:
            chips = ["Bay từ TP.HCM", "Bay từ Hà Nội", "Đổi chỗ ở"]
            self.notes.append(f"Bạn bay từ đâu tới {self.trip.place} nè?")
        text = " ".join([lead, *self.notes])
        return Answer(
            kind="answer",
            text=text,
            lead=lead,
            cards=[
                Card(
                    ref="r1",
                    id=f"plan:{normalize_text(self.trip.place).replace(' ', '-')}",
                    kind="itinerary",
                    title=f"{self.trip.place} {days} ngày",
                    price_from=None,
                    price_basis="unavailable",
                    observed_at=datetime.now(UTC),
                    lines=lines,
                    source=ATTRIBUTION,
                    actions=[
                        self._booking_action(
                            self.trip.stay, self.trip.transport, self.trip.return_transport
                        )
                    ]
                    if self.trip.stay
                    and self.trip.stay.source == "tripflix"
                    and self.trip.transport
                    and self.trip.transport.flight_id
                    and self.trip.transport.fare_code
                    else None,
                )
            ],
            facts=[
                {
                    "ref": "r1",
                    "kind": "itinerary",
                    "destination": self.trip.place,
                    "from": base_name,
                    "days": days_facts,
                    "estimate": True,
                    "notes": [*assumptions, *self.notes],
                    "services": [s.name for s in [self.trip.stay] if s]
                    + [f.summary for f in [self.trip.transport, self.trip.return_transport] if f],
                }
            ],
            suggestions=chips[:3],
        )

    def _flight_line(self, flight: DraftTransport, day: int) -> CardLine:
        times = "–".join(t for t in [flight.depart_time, flight.arrive_time] if t)
        return CardLine(
            label=f"Ngày {day} · ✈ Bay {flight.from_airport} → {flight.to_airport} {times}".strip(),
            detail=flight.summary,
            service="flight",
        )

    def _booking_action(
        self,
        stay: DraftChoice | None,
        flight: DraftTransport | None,
        returning: DraftTransport | None = None,
    ) -> CardAction:
        params = {"destination": self.trip.place, "adults": str(self.trip.adults)}
        start = self.trip.date_from or (flight.flight_date if flight else None)
        if start:
            params["startDate"] = start.isoformat()
        if self.trip.days:
            params["days"] = str(len(self.trip.days))
        if stay and stay.source == "tripflix" and self.trip.date_from and self.trip.date_to:
            params.update(
                hotelId=stay.id,
                hotelName=stay.name,
                checkIn=self.trip.date_from.isoformat(),
                nights=str((self.trip.date_to - self.trip.date_from).days),
            )
        if flight and flight.flight_date and flight.from_airport and flight.to_airport:
            params.update(
                flightFrom=flight.from_airport,
                flightTo=flight.to_airport,
                flightDate=flight.flight_date.isoformat(),
            )
        if returning and returning.flight_date and returning.from_airport and returning.to_airport:
            params.update(
                returnFrom=returning.from_airport,
                returnTo=returning.to_airport,
                returnDate=returning.flight_date.isoformat(),
            )
        return CardAction(
            type="book", label="Đặt theo lộ trình", path="/trip-builder", params=params
        )

    async def _render(self) -> Answer:
        base = await self._base()
        if base is None:
            return Answer(kind="no_result", text=f"Tripi chưa định vị được {self.trip.place}.")
        return self._itinerary_answer(*base, ["Quãng đường và thời gian là ước tính."])

    # ---- stays: Tripflix first, outside ones after and labelled (X1, Bảo 16/11)

    async def stay_options(
        self, understood: Understanding, *, tripflix_only: bool = False
    ) -> Answer:
        place = understood.place or self.trip.place
        if not place:
            return Answer(kind="clarify", text="Bạn muốn tìm chỗ ở tại đâu?")
        self.trip.place = place
        wanted = understood.model_copy(update={"place": place})
        dates = planner.stay_range(wanted, self.today)
        if dates is None and self.trip.date_from and self.trip.date_from >= self.today:
            end = self.trip.date_to or self.trip.date_from + timedelta(days=1)
            dates = (self.trip.date_from, max(end, self.trip.date_from + timedelta(days=1)))
        if dates is None:
            wanted = wanted.model_copy(update={"day_ref": "this_weekend", "nights": 1})
            dates = planner.stay_range(wanted, self.today)
            self.notes.append("Tripi tạm xem giá cuối tuần này, 1 đêm.")
        if isinstance(dates, planner.DateProblem):
            return Answer(kind="clarify", text=dates.question)
        assert dates is not None
        self.trip.date_from, self.trip.date_to = dates
        wanted = wanted.model_copy(update={"check_in": dates[0], "check_out": dates[1]})
        if not tripflix_only:
            self.trip.pending_flights = []
        found = await search_stays(self.core, wanted)
        current = self.trip.stay.id if self.trip.stay else ""
        options = [
            DraftChoice(ref="", source="tripflix", id=c.id, name=c.title[:120])
            for c in found.cards
            if c.kind == "stay" and c.id != current
        ][:TRIPFLIX_OPTIONS]
        prices = {c.id: c.price_from for c in found.cards}
        taken = {normalize_text(o.name) for o in options}
        lodging = (
            []
            if tripflix_only
            else await self.places.search(city=place, kinds=["lodging"], limit=5)
        )
        outside = [
            DraftChoice(
                ref="",
                source="external",
                id=p.id,
                name=p.name[:120],
                lat=_round(p.latitude),
                lng=_round(p.longitude),
            )
            for p in lodging
            if p.kind == "lodging" and normalize_text(p.name) not in taken and p.id != current
        ][:EXTERNAL_OPTIONS]
        options = [
            o.model_copy(update={"ref": f"o{i}"}) for i, o in enumerate([*options, *outside], 1)
        ]
        if not options:
            return Answer(kind="no_result", text=f"Tripi chưa tìm được chỗ ở khác ở {place}.")
        self.trip.pending = options

        def detail(option: DraftChoice) -> str:
            if option.source == "external":
                return "Ngoài Tripflix · tham khảo, chưa đặt được trên Tripflix"
            price = prices.get(option.id)
            return f"Tripflix · từ {vnd(int(price))}/đêm" if price is not None else "Tripflix"

        lines = [CardLine(label=o.name, detail=detail(o), ref=o.ref) for o in options]
        lead = f"Đây là mấy chỗ ở {place} bạn chọn thử nha, chỗ có trên Tripflix xếp trước."
        return Answer(
            kind="answer",
            text=" ".join([lead, *self.notes]),
            lead=lead,
            cards=[
                Card(
                    ref="r1",
                    id=f"compare:{normalize_text(place).replace(' ', '-')}",
                    kind="compare",
                    title="Chọn chỗ ở",
                    price_from=None,
                    price_basis="unavailable",
                    check_in=dates[0],
                    check_out=dates[1],
                    observed_at=datetime.now(UTC),
                    lines=lines,
                    actions=[CardAction(type="select", label="Chọn", ref=o.ref) for o in options],
                )
            ],
            # No prices for the Responder (Verifier V2): names and where they come from only.
            facts=[
                {
                    "ref": "r1",
                    "kind": "compare",
                    "options": [
                        {"ref": o.ref, "name": o.name, "source": o.source} for o in options
                    ],
                }
            ],
        )

    async def select(self, ref: str = "", ordinal: int | None = None, message: str = "") -> Answer:
        flights = self.trip.pending_flights
        text = normalize_text(message)
        wants_stay = bool(re.search(r"\b(khach san|ks|phong|cho o|resort|homestay|villa)\b", text))
        pick_flight = not wants_stay and (
            bool(re.search(r"\b(chuyen|bay|ve|may bay|flight)\b", text)) or bool(flights)
        )
        flight = next((f for f in flights if f.ref == ref), None) if ref else None
        if not ref and pick_flight and ordinal and 0 < ordinal <= len(flights):
            flight = flights[ordinal - 1]
        if flight is not None:
            self.trip.transport = flight.model_copy(update={"ref": ""})
            self.trip.pending_flights = []
            if self.trip.days:
                return await self._build(len(self.trip.days))
            return self._review(Answer(kind="answer", text=f"Đã chọn {flight.summary} nha."))
        pending = self.trip.pending
        choice = next((o for o in pending if o.ref == ref), None) if ref else None
        if not ref and not pick_flight and ordinal and 0 < ordinal <= len(pending):
            choice = pending[ordinal - 1]
        if choice is None:
            return Answer(kind="clarify", text="Bạn chọn chỗ nào trong danh sách vừa rồi nè?")
        if choice.source == "tripflix":
            response = await self.core.get(f"/api/hotels/{choice.id}")
            if response.status_code == httpx.codes.NOT_FOUND:
                return Answer(kind="no_result", text=f"{choice.name} không còn bán trên Tripflix.")
            response.raise_for_status()
            location = response.json().get("location") or {}
            if location.get("lat") is not None and location.get("lng") is not None:
                choice = choice.model_copy(
                    update={"lat": _round(location["lat"]), "lng": _round(location["lng"])}
                )
        self.trip.ops = [*self.trip.ops, DraftOp(op="set_stay", stay=self.trip.stay)][-5:]
        self.trip.stay = choice.model_copy(update={"ref": ""})
        self.trip.pending = []
        if self.trip.days:
            return await self._build(len(self.trip.days))
        lead = f"Đã chọn {choice.name} nha."
        return self._review(
            Answer(
                kind="answer",
                text=f"{lead} Muốn mình xếp lộ trình từ chỗ này luôn không?",
                lead=lead,
                suggestions=["Xếp lộ trình", "Cách đi tới đó"],
            )
        )

    def _review(self, answer: Answer) -> Answer:
        if not (self.trip.stay and self.trip.stay.source == "tripflix") and not (
            self.trip.transport and self.trip.transport.flight_id
        ):
            return answer
        lead = answer.lead or answer.text
        answer.text = f"{answer.text} {REVIEW_QUESTION}"
        answer.lead = f"{lead} {REVIEW_QUESTION}"
        answer.suggestions = REVIEW_CHIPS.copy()
        return answer

    async def confirm(self) -> Answer:
        stay, flight = self.trip.stay, self.trip.transport
        has_stay = stay is not None and stay.source == "tripflix"
        has_flight = flight is not None and flight.mode == "flight" and bool(flight.flight_id)
        if not has_stay and not has_flight:
            return Answer(
                kind="clarify",
                text="Bạn chọn chỗ ở trên Tripflix hoặc một chuyến bay trước khi chốt nha.",
                suggestions=["Đổi chỗ ở", "Đổi chuyến bay"],
            )
        lines: list[CardLine] = []
        actions: list[CardAction] = []
        checked_stay, checked_flight, checked_return = None, None, None
        notes: list[str] = []
        if has_stay and stay:
            start, end = self.trip.date_from, self.trip.date_to
            if start is None or end is None or start < self.today or end <= start:
                notes.append("Bạn cho mình ngày nhận và trả phòng mới để kiểm tra nha.")
            else:
                checked = await hotel_room(self.core, stay.id, start, end, self.trip.adults)
                if checked.kind == "answer":
                    card = checked.cards[0]
                    lines.append(CardLine(label=card.title, detail=f"{start:%d/%m}–{end:%d/%m}"))
                    checked_stay = stay.model_copy(update={"name": card.title})
                else:
                    notes.append(f"{stay.name} hết phòng hoặc không còn bán. Bạn đổi chỗ ở nha.")
        if has_flight and flight:
            available = await self._check_flight(flight)
            if available:
                assert flight.flight_date and flight.from_airport and flight.to_airport
                lines.append(CardLine(label=available, detail=f"{flight.flight_date:%d/%m}"))
                checked_flight = flight
            else:
                notes.append("Chuyến hoặc hạng vé đã chọn không còn chỗ. Bạn đổi chuyến bay nha.")
        returning = self.trip.return_transport
        if returning and returning.flight_id:
            available = await self._check_flight(returning)
            if available:
                checked_return = returning
                lines.append(
                    CardLine(
                        label=available,
                        detail=f"{returning.flight_date:%d/%m}" if returning.flight_date else "",
                    )
                )
            else:
                notes.append(
                    "Chuyến về hoặc hạng vé đã chọn không còn chỗ. Bạn chọn lại chuyến về nha."
                )
        if lines:
            actions.append(self._booking_action(checked_stay, checked_flight, checked_return))
        lead = f"Chốt chuyến {self.trip.place} nè, mình vừa kiểm tra lại phòng và vé."
        return Answer(
            kind="answer" if actions else "no_result",
            text=" ".join([lead, *notes]),
            lead=" ".join([lead, *notes]),
            cards=[
                Card(
                    ref="r1",
                    id="booking",
                    kind="booking",
                    title=f"Chốt chuyến {self.trip.place}",
                    price_from=None,
                    price_basis="unavailable",
                    observed_at=datetime.now(UTC),
                    lines=lines,
                    actions=actions,
                )
            ],
            facts=[
                {
                    "ref": "r1",
                    "kind": "booking",
                    "available": [a.label for a in actions],
                    "notes": notes,
                }
            ],
            suggestions=REVIEW_CHIPS.copy(),
        )

    async def _check_flight(self, flight: DraftTransport) -> str | None:
        if not (
            flight.flight_date
            and flight.flight_date >= self.today
            and flight.from_airport
            and flight.to_airport
            and flight.passengers
            and flight.fare_code
        ):
            return None
        response = await self.core.get(
            "/api/flights",
            params={
                "from": flight.from_airport,
                "to": flight.to_airport,
                "date": flight.flight_date.isoformat(),
                "passengers": flight.passengers,
            },
        )
        response.raise_for_status()
        for offer in Flights.model_validate(response.json()).flights:
            if (
                offer.productId == flight.flight_id
                and offer.isAvailable
                and any(
                    f.code == flight.fare_code and f.totalPrice is not None for f in offer.fares
                )
            ):
                return flight_title(offer)
        return None

    # ---- small edits on the plan

    async def move_stop(
        self,
        name: str,
        *,
        anchor_name: str = "",
        placement: Literal["before", "after"] | None = None,
        target_day: int | None = None,
        target_slot: Slot | None = None,
    ) -> Answer:
        if not self.trip.days:
            return Answer(
                kind="clarify", text="Mình chưa có lộ trình nào để sửa. Xếp lộ trình mới nha?"
            )

        def find(wanted: str) -> list[tuple[int, int, DraftStop]]:
            folded = normalize_text(wanted)
            matches = [
                (day, position, stop)
                for day, stops in enumerate(self.trip.days)
                for position, stop in enumerate(stops)
                if folded and folded in normalize_text(stop.name)
            ]
            exact = [item for item in matches if normalize_text(item[2].name) == folded]
            return exact or matches

        matches = find(name)
        if len(matches) != 1:
            return Answer(
                kind="clarify",
                text=f"Bạn nói rõ tên điểm «{name[:60]}» trong lộ trình giúp mình nha.",
            )
        day, position, stop = matches[0]
        anchor = None
        if anchor_name:
            anchors = find(anchor_name)
            if len(anchors) != 1 or not placement or anchors[0][2].id == stop.id:
                return Answer(
                    kind="clarify",
                    text=f"Bạn nói rõ điểm mốc «{anchor_name[:60]}» và đặt trước hay sau nha.",
                )
            destination, _, anchor = anchors[0]
            slot = anchor.slot
        elif target_day is not None or target_slot is not None:
            destination = target_day - 1 if target_day is not None else day
            slot = target_slot or stop.slot
        else:
            return Answer(
                kind="clarify", text="Bạn muốn chuyển điểm sang ngày, buổi hay trước điểm nào?"
            )
        if not 0 <= destination < len(self.trip.days):
            return Answer(
                kind="clarify", text="Ngày đó chưa có trong lộ trình, bạn chọn lại ngày nha."
            )
        outbound, inbound = self.trip.transport, self.trip.return_transport
        allowed = travel_slots(
            arrival=outbound.arrive_time if destination == 0 and outbound else None,
            departure=(
                inbound.depart_time if destination == len(self.trip.days) - 1 and inbound else None
            ),
        )
        if slot not in allowed:
            return Answer(
                kind="clarify",
                text=f"Khung giờ bay ngày {destination + 1} không đủ thời gian cho buổi {slot}. "
                "Bạn chọn buổi khác để kịp giờ bay nha.",
            )
        days = [stops.copy() for stops in self.trip.days]
        del days[day][position]
        stops = days[destination]
        if anchor is not None:
            insertion = next(i for i, item in enumerate(stops) if item.id == anchor.id)
            insertion += placement == "after"
            relation = "lên trước" if placement == "before" else "ra sau"
            note = f"Đã chuyển {stop.name} {relation} {anchor.name}."
        else:
            slots = ["sáng", "trưa", "chiều", "tối"]
            same_slot = [i for i, item in enumerate(stops) if item.slot == slot]
            insertion = (
                same_slot[-1] + 1
                if same_slot
                else next(
                    (
                        i
                        for i, item in enumerate(stops)
                        if slots.index(item.slot) > slots.index(slot)
                    ),
                    len(stops),
                )
            )
            note = f"Đã chuyển {stop.name} sang ngày {destination + 1}, buổi {slot}."
        stops.insert(insertion, stop.model_copy(update={"slot": slot}))
        if [[(s.id, s.slot) for s in day] for day in days] == [
            [(s.id, s.slot) for s in day] for day in self.trip.days
        ]:
            text = f"{stop.name} đã ở vị trí đó rồi nha."
            if anchor:
                relation = "trước" if placement == "before" else "sau"
                text = f"{stop.name} đã ở {relation} {anchor.name} rồi nha."
            return Answer(kind="clarify", text=text)
        self.trip.ops = [
            *self.trip.ops,
            DraftOp(op="move_stop", stop=stop, day=day, position=position),
        ][-5:]
        self.trip.days = days
        self.notes.append(note)
        return await self._render()

    async def remove_stop(self, name: str = "", stop_id: str = "") -> Answer:
        wanted = normalize_text(name)
        for day_index, stops in enumerate(self.trip.days):
            for position, stop in enumerate(stops):
                if (stop_id and stop.id == stop_id) or (
                    wanted and wanted in normalize_text(stop.name)
                ):
                    self.trip.ops = [
                        *self.trip.ops,
                        DraftOp(op="remove_stop", stop=stop, day=day_index, position=position),
                    ][-5:]
                    del stops[position]
                    self.notes.append(f"Đã bỏ {stop.name} khỏi lộ trình.")
                    return await self._render()
        if not self.trip.days:
            return Answer(
                kind="clarify", text="Mình chưa có lộ trình nào để sửa. Xếp lộ trình mới nha?"
            )
        return Answer(
            kind="clarify",
            text=f"Mình chưa thấy «{name[:60]}» trong lộ trình, bạn nói lại tên điểm nha.",
        )

    async def undo(self) -> Answer:
        if not self.trip.ops:
            return Answer(kind="answer", text="Chưa có thay đổi nào để hoàn tác nè.")
        op = self.trip.ops[-1]
        self.trip.ops = self.trip.ops[:-1]
        if op.op == "move_stop" and op.stop is not None and op.day is not None:
            for stops in self.trip.days:
                stops[:] = [stop for stop in stops if stop.id != op.stop.id]
            if op.day < len(self.trip.days):
                self.trip.days[op.day].insert(op.position or 0, op.stop)
            self.notes.append(f"Đã trả {op.stop.name} về vị trí trước.")
            return await self._render()
        if op.op == "remove_stop" and op.stop is not None and op.day is not None:
            if op.day < len(self.trip.days):
                self.trip.days[op.day].insert(op.position or 0, op.stop)
            self.notes.append(f"Đã thêm lại {op.stop.name}.")
            return await self._render()
        self.trip.stay = op.stay
        self.notes.append("Đã quay lại chỗ ở trước.")
        if self.trip.days:
            return await self._build(len(self.trip.days))
        return Answer(kind="answer", text=" ".join(self.notes))

    # ---- how to get there: flights when both cities have one, else sample bus routes

    async def transport(self, understood: Understanding) -> Answer:
        origin = understood.from_city or self.trip.origin_city
        destination = understood.to_city or understood.place or self.trip.place
        if not origin:
            self.trip.awaiting = Awaiting(intent="change_transport", missing="origin")
            return Answer(kind="clarify", text="Bạn xuất phát từ đâu nè?")
        if not destination:
            self.trip.awaiting = Awaiting(intent="change_transport", missing="place")
            return Answer(kind="clarify", text="Bạn muốn đi tới đâu nè?")
        self.trip.origin_city, self.trip.place = origin[:60], self.trip.place or destination
        self.trip.pending_flights = []
        if await find_airport(self.core, origin) and await find_airport(self.core, destination):
            travel_date = (
                understood.flight_date
                or planner.start_day(understood, self.today)
                or self.trip.date_from
            )
            if travel_date is None:
                self.trip.awaiting = Awaiting(intent="change_transport", missing="dates")
                return Answer(
                    kind="clarify",
                    text=f"Có chuyến bay {origin} – {destination} trên Tripflix, bạn bay ngày nào?",
                )
            flights = await search_flights(
                self.core,
                understood.model_copy(
                    update={
                        "intent": "find_flight",
                        "from_city": origin,
                        "to_city": destination,
                        "flight_date": travel_date,
                        "adults": self.trip.adults,
                    }
                ),
            )
            if flights.cards:
                self.trip.pending_flights = draft_flights(flights.cards)
            return flights
        routes = bus_routes(origin, destination)
        if not routes:
            return Answer(
                kind="no_result",
                text=f"Tripi chưa có dữ liệu chuyến bay hay tuyến xe từ {origin} "
                f"tới {destination}.",
            )
        start, end = (
            await self.weather.find_place(origin),
            await self.weather.find_place(destination),
        )
        leg = (
            estimate_leg((start.latitude, start.longitude), (end.latitude, end.longitude))
            if start and end
            else None
        )
        duration = (
            f" · khoảng {leg.minutes // 60} giờ {leg.minutes % 60} phút (ước tính)" if leg else ""
        )
        self.trip.transport = DraftTransport(
            mode="bus", summary=f"Xe khách {routes[0].from_station} – {routes[0].to_station}"[:160]
        )
        lead = f"Từ {origin} đi {destination} bạn có thể đi xe khách nè."
        return Answer(
            kind="answer",
            text=f"{lead} Đây là thông tin tham khảo, chưa đặt được trên Tripflix.",
            lead=lead,
            cards=[
                Card(
                    ref="r1",
                    id=f"bus:{normalize_text(origin)}-{normalize_text(destination)}".replace(
                        " ", "-"
                    ),
                    kind="transport",
                    title=f"Xe khách {origin} – {destination}",
                    price_from=None,
                    price_basis="unavailable",
                    observed_at=datetime.now(UTC),
                    lines=[
                        CardLine(
                            label=f"{r.from_station} → {r.to_station}", detail=f"{r.kind}{duration}"
                        )
                        for r in routes
                    ],
                    source=attribution(),
                )
            ],
            facts=[
                {
                    "ref": "r1",
                    "kind": "transport",
                    "mode": "bus",
                    "from": origin,
                    "to": destination,
                    "stations": [[r.from_station, r.to_station] for r in routes],
                    "minutes": leg.minutes if leg else None,
                    "estimate": True,
                    "reference": True,
                }
            ],
            suggestions=["Xếp lộ trình", "Chọn chỗ ở"],
        )
