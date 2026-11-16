"""Stage B Skills (plan B6, B7): plan a whole trip, then edit it by small operations.

Code decides every name, distance and option; the Responder only says them. Edits are
operations on the trip memory the app keeps (DeepResearch trợ lý đầy đủ §5): pick a stay,
drop a stop, undo. Coordinates of the user never go anywhere: the origin is a city name.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

import httpx

from app.clients.places import ATTRIBUTION, PlacesClient, PointOfInterest
from app.clients.weather import WeatherClient
from app.services.assistant import planner
from app.services.assistant.itinerary import Slot, build_itinerary
from app.services.assistant.route import estimate_leg
from app.services.assistant.schemas import (
    Answer,
    Card,
    CardLine,
    DraftChoice,
    DraftOp,
    DraftStop,
    DraftTransport,
    TripContext,
    Understanding,
)
from app.services.assistant.skills import weather as weather_skill
from app.services.assistant.skills.flight import find_airport, search_flights
from app.services.assistant.skills.stay import search_stays, vnd
from app.services.assistant.transport import attribution, bus_routes
from app.services.summary.vi_text import normalize_text

DEFAULT_DAYS = 2  # "đi Vũng Tàu" alone: plan 2 days and say so [HIỆU CHỈNH]
MAX_DAYS = 7
TRIPFLIX_OPTIONS = 3
EXTERNAL_OPTIONS = 1
COORD_DIGITS = 5  # about 1 m; keeps the trip memory small
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
        centre = await self.weather.find_place(self.trip.place)
        if centre is None:
            return None
        return (centre.latitude, centre.longitude), f"trung tâm {self.trip.place}"

    async def _rain_by_day(self, days: int) -> list[int | None]:
        start = self.trip.date_from
        if start is None or start < self.today:
            return []
        window = planner.DayWindow(start, start + timedelta(days=days - 1), False, False)
        found = await weather_skill.forecast(self.weather, self.trip.place, window)
        by_day = {d.day: d.rain_chance for d in found.days or []}
        return [by_day.get(start + timedelta(days=i)) for i in range(days)]

    # ---- the plan

    async def plan(self, understood: Understanding) -> Answer:
        place = understood.place or self.trip.place
        if not place:
            return Answer(kind="clarify", text="Bạn muốn đi đâu nè? Mình xếp lộ trình luôn cho.")
        if place != self.trip.place:
            self.trip = TripContext(origin_city=self.trip.origin_city, place=place)
        if understood.interests:
            self.trip.interests = [t for t in understood.interests if t in INTEREST_TAGS][:5]
        days = self._days(understood)
        self.trip.ops = []  # a new plan: nothing to undo
        return await self._build(days, pace=understood.pace or "relaxed")

    def _days(self, understood: Understanding) -> int:
        if understood.nights is not None:
            return max(1, min(MAX_DAYS, understood.nights + 1))
        if self.trip.date_from and self.trip.date_to:
            return max(1, min(MAX_DAYS, (self.trip.date_to - self.trip.date_from).days + 1))
        if self.trip.days:
            return len(self.trip.days)
        self.notes.append(f"Tripi tạm xếp {DEFAULT_DAYS} ngày, bạn muốn đi mấy ngày cứ nói nha.")
        return DEFAULT_DAYS

    async def _build(self, days: int, *, pace: str = "relaxed") -> Answer:
        base = await self._base()
        if base is None:
            return Answer(kind="no_result", text=f"Tripi chưa định vị được {self.trip.place}.")
        point, base_name = base
        candidates = await self.places.search(
            city=self.trip.place, kinds=["see", "food", "cafe"], limit=60
        )
        rain = await self._rain_by_day(days)
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
        self.notes += [note for day in plan.days for note in day.notes]
        return self._itinerary_answer(point, base_name, plan.assumptions)

    def _itinerary_answer(
        self, base: tuple[float, float], base_name: str, assumptions: Sequence[str]
    ) -> Answer:
        lines, days_facts = [], []
        for index, stops in enumerate(self.trip.days, 1):
            previous, facts = base, []
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
        days = len(self.trip.days)
        lead = f"Lộ trình {self.trip.place} {days} ngày đây nè, xếp từ {base_name}."
        chips = ["Đổi chỗ ở", "Thời tiết những ngày đó"]
        if not self.trip.origin_city:
            chips.insert(0, "Mình đi từ TP.HCM")
            self.notes.append("Bạn xuất phát từ đâu để mình gợi ý cách đi nha?")
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
                }
            ],
            suggestions=chips[:3],
        )

    async def _render(self) -> Answer:
        base = await self._base()
        if base is None:
            return Answer(kind="no_result", text=f"Tripi chưa định vị được {self.trip.place}.")
        return self._itinerary_answer(*base, ["Quãng đường và thời gian là ước tính."])

    # ---- stays: Tripflix first, outside ones after and labelled (X1, Bảo 16/11)

    async def stay_options(self, understood: Understanding) -> Answer:
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
        wanted = wanted.model_copy(update={"check_in": dates[0], "check_out": dates[1]})
        found = await search_stays(self.core, wanted)
        current = self.trip.stay.id if self.trip.stay else ""
        options = [
            DraftChoice(ref="", source="tripflix", id=c.id, name=c.title[:120])
            for c in found.cards
            if c.kind == "stay" and c.id != current
        ][:TRIPFLIX_OPTIONS]
        prices = {c.id: c.price_from for c in found.cards}
        taken = {normalize_text(o.name) for o in options}
        outside = [
            DraftChoice(
                ref="",
                source="external",
                id=p.id,
                name=p.name[:120],
                lat=_round(p.latitude),
                lng=_round(p.longitude),
            )
            for p in await self.places.search(city=place, kinds=["lodging"], limit=5)
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

    async def select(self, ref: str = "", ordinal: int | None = None) -> Answer:
        pending = self.trip.pending
        choice = next((o for o in pending if o.ref == ref), None) if ref else None
        if choice is None and ordinal and 0 < ordinal <= len(pending):
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
        return Answer(
            kind="answer",
            text=f"{lead} Muốn mình xếp lộ trình từ chỗ này luôn không?",
            lead=lead,
            suggestions=["Xếp lộ trình", "Cách đi tới đó"],
        )

    # ---- small edits on the plan

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
            return Answer(kind="clarify", text="Bạn xuất phát từ đâu nè?")
        if not destination:
            return Answer(kind="clarify", text="Bạn muốn đi tới đâu nè?")
        self.trip.origin_city, self.trip.place = origin[:60], self.trip.place or destination
        if await find_airport(self.core, origin) and await find_airport(self.core, destination):
            if self.trip.date_from is None and understood.flight_date is None:
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
                        "flight_date": understood.flight_date or self.trip.date_from,
                        "adults": self.trip.adults,
                    }
                ),
            )
            if flights.cards:
                self.trip.transport = DraftTransport(
                    mode="flight", summary=f"Bay {origin} – {destination}"
                )
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
