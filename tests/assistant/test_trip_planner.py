"""Stage B through the real Turn (plan B6, B7): plan, pick a stay, edit, undo, get there.

Places, weather and Core are fakes; Vũng Tàu points are simulated (approximate coordinates).
"""

import asyncio
import json
from collections.abc import Sequence
from datetime import date, timedelta
from uuid import uuid4

import httpx

from app.clients.places import PointOfInterest
from app.clients.weather import DayWeather, Place
from app.services.assistant import planner
from app.services.assistant.schemas import ChatRequest, DraftAction, TripContext, Understanding
from app.services.assistant.turn import Turn

TODAY = planner.today_in_vietnam()
CENTRE = Place("Vũng Tàu", 10.3460, 107.0843)
SAIGON = Place("TP.HCM", 10.7769, 106.7009)


def poi(pid, name, lat, lng, kind="see", tags=(), popularity=0.5):
    return PointOfInterest(pid, name, kind, lat, lng, "Vũng Tàu", tuple(tags), popularity)


POINTS = [
    poi("osm:1", "Hải Đăng", 10.3333, 107.0778, tags=("viewpoint",), popularity=0.9),
    poi("osm:2", "Mũi Nghinh Phong", 10.3236, 107.0843, tags=("sunset",), popularity=0.8),
    poi("osm:3", "Tượng Chúa Kitô", 10.3271, 107.0860, tags=("viewpoint",), popularity=0.85),
    poi("osm:4", "Bãi Sau", 10.3487, 107.0938, tags=("beach",), popularity=0.9),
    poi("osm:5", "Bạch Dinh", 10.3530, 107.0680, tags=("museum",), popularity=0.6),
    poi("osm:6", "Hồ Mây", 10.3460, 107.0710, tags=("park",), popularity=0.7),
    poi("osm:7", "Quán hải sản", 10.3450, 107.0720, kind="food", popularity=0.7),
    poi("osm:8", "Cafe biển", 10.3330, 107.0830, kind="cafe", popularity=0.6),
]
LODGING = [poi("osm:9", "Nhà nghỉ Biển Xanh", 10.3490, 107.0950, kind="lodging")]


class FakePlaces:
    def __init__(self, points=POINTS):
        self.points = points

    async def search(
        self,
        *,
        city: str = "",
        near: tuple[float, float] | None = None,
        kinds: Sequence[str] = (),
        radius_km: float = 15,
        limit: int = 40,
    ) -> list[PointOfInterest]:
        pool = LODGING if "lodging" in kinds else self.points
        return [p for p in pool if p.kind in kinds][:limit]


class FakeWeather:
    async def find_place(self, name):
        return SAIGON if "HCM" in name or "sai gon" in name.lower() else CENTRE

    async def forecast(self, place, start, end):
        return [DayWeather(start, 25, 31, 20, "có mây")]


def core(calls: list[str], *, airports: dict[str, str] | None = None) -> httpx.AsyncClient:
    airports = airports or {}

    def handle(request: httpx.Request) -> httpx.Response:
        path, params = request.url.path, request.url.params
        calls.append(path)
        if path == "/api/suggest" and params.get("types") == "airport":
            code = airports.get(params["q"])
            items = [{"type": "airport", "refId": code, "name": code}] if code else []
            return httpx.Response(200, json={"items": items})
        if path == "/api/suggest":
            return httpx.Response(200, json={"items": [{"type": "place", "refId": "vt"}]})
        if path == "/api/stays":
            items = [
                {"hotelId": f"h{i}", "name": f"Khách sạn {i}", "unitPrice": 500_000 + i,
                 "totalPrice": 500_000 + i}
                for i in (1, 2, 3, 4)
            ]  # fmt: skip
            return httpx.Response(200, json={"items": items})
        if path.startswith("/api/hotels/"):
            return httpx.Response(
                200,
                json={"id": "h1", "name": "Khách sạn 1", "location": {"lat": 10.35, "lng": 107.09}},
            )
        if path == "/api/flights":
            return httpx.Response(200, json={"flights": []})
        return httpx.Response(404)

    return httpx.AsyncClient(base_url="https://core.test", transport=httpx.MockTransport(handle))


def run(
    parsed: Understanding | None,
    trip: TripContext | None = None,
    action: DraftAction | None = None,
    *,
    airports=None,
    places=None,
    message="...",
):
    calls: list[str] = []
    request = ChatRequest(conversation_id=uuid4(), message=message, trip=trip, action=action)

    async def go():
        async with core(calls, airports=airports) as client:
            turn = Turn(
                request,
                parsed,
                core=client,
                weather=FakeWeather(),
                today=TODAY,
                places=places or FakePlaces(),
            )
            answer = await turn.answer()
            return answer, turn.next_trip(answer)

    answer, memory = asyncio.run(go())
    return answer, memory, calls


def plan_vung_tau():
    return run(
        Understanding(intent="plan_trip", place="Vũng Tàu", nights=1), message="cứ lên trước"
    )


def test_plan_trip_builds_a_two_day_itinerary_with_estimates_and_asks_the_origin():
    answer, trip, _ = plan_vung_tau()
    card = answer.cards[0]
    assert card.kind == "itinerary" and card.source and "OpenStreetMap" in card.source
    assert len(trip.days) == 2 and all(trip.days)
    assert (answer.lead or "").startswith("Lộ trình Vũng Tàu 2 ngày")
    assert all("km" in line.detail and "phút" in line.detail for line in card.lines or [])
    assert answer.facts[0]["estimate"] is True
    assert "Bay từ TP.HCM" in answer.suggestions
    assert "Bay từ Hà Nội" in answer.suggestions


def test_no_places_with_coordinates_is_said_not_invented():
    answer, trip, _ = run(
        Understanding(intent="plan_trip", place="Vũng Tàu", nights=1),
        places=FakePlaces([]),
        message="cứ lên trước",
    )
    assert answer.kind == "no_result" and answer.cards == [] and trip.days == []


def test_stay_options_put_tripflix_first_and_label_outside_ones_without_price():
    _, trip, _ = plan_vung_tau()
    answer, trip, _ = run(Understanding(intent="change_stay"), trip)
    card = answer.cards[0]
    assert card.kind == "compare"
    refs = [line.ref for line in card.lines or []]
    assert refs == ["o1", "o2", "o3", "o4"]
    assert "Tripflix · từ" in (card.lines or [])[0].detail
    assert "Ngoài Tripflix" in (card.lines or [])[-1].detail
    assert "500" not in json.dumps(answer.facts)  # no price reaches the Responder
    assert [o.source for o in trip.pending] == ["tripflix"] * 3 + ["external"]


def test_tapping_choose_needs_no_llm_and_replans_from_the_new_stay():
    _, trip, _ = plan_vung_tau()
    _, trip, _ = run(Understanding(intent="change_stay"), trip)
    answer, trip, calls = run(None, trip, DraftAction(type="select", ref="o1"))
    assert "/api/hotels/h1" in calls  # checked again with Core before use
    assert trip.stay is not None and trip.stay.lat == 10.35
    assert trip.pending == [] and trip.ops[-1].op == "set_stay"
    assert "Khách sạn 1" in (answer.lead or "")


def test_remove_a_stop_then_undo_puts_it_back_in_place():
    _, trip, _ = plan_vung_tau()
    first = trip.days[0][0]
    _, removed, _ = run(Understanding(intent="remove_stop", stop_name=first.name), trip)
    assert first.id not in [s.id for day in removed.days for s in day]
    _, restored, _ = run(None, removed, DraftAction(type="undo"))
    assert restored.days[0][0].id == first.id and restored.ops == []


def test_unknown_stop_is_asked_about():
    _, trip, _ = plan_vung_tau()
    answer, _, _ = run(Understanding(intent="remove_stop", stop_name="Phố đi bộ"), trip)
    assert answer.kind == "clarify" and "Phố đi bộ" in answer.text


def test_no_airport_means_a_reference_bus_route_with_an_estimated_time():
    _, trip, _ = plan_vung_tau()
    answer, trip, calls = run(
        Understanding(intent="change_transport", from_city="TP.HCM"),
        trip,
        airports={"TP.HCM": "SGN"},
    )
    card = answer.cards[0]
    assert card.kind == "transport" and "Tham khảo" in (card.source or "")
    assert "Bến xe Miền Đông → Bến xe Vũng Tàu" in [line.label for line in card.lines or []]
    assert "ước tính" in (card.lines or [])[0].detail
    assert "/api/flights" not in calls
    assert trip.origin_city == "TP.HCM" and trip.transport and trip.transport.mode == "bus"


def test_flights_are_offered_when_both_cities_have_an_airport():
    trip = TripContext(place="Đà Nẵng", date_from=TODAY + timedelta(days=5))
    _, _, calls = run(
        Understanding(intent="change_transport", from_city="Hà Nội", place="Đà Nẵng"),
        trip,
        airports={"Hà Nội": "HAN", "Đà Nẵng": "DAD"},
    )
    assert "/api/flights" in calls


def test_the_plan_stays_small_enough_for_the_app_to_keep():
    _, trip, _ = plan_vung_tau()
    _, trip, _ = run(Understanding(intent="change_stay"), trip)
    size = len(trip.model_dump_json(by_alias=True, exclude_none=True).encode())
    assert size < 1800  # the app keeps the whole chat in 2,048 bytes


def test_an_old_app_trip_v1_is_still_read():
    old = {"v": 1, "place": "Đà Lạt", "adults": 2, "lastCards": [], "asked": False}
    request = ChatRequest.model_validate(
        {"conversationId": str(uuid4()), "message": "hi", "trip": old}
    )
    assert request.trip and request.trip.place == "Đà Lạt" and request.trip.days == []


def test_a_new_place_drops_the_old_plan():
    _, trip, _ = plan_vung_tau()
    _, moved, _ = run(Understanding(intent="find_reel", place="Đà Lạt", query="Đà Lạt"), trip)
    assert moved.place == "Đà Lạt" and moved.days == [] and moved.stay is None


def test_dates_are_not_needed_to_plan():
    assert date.today()  # plan_vung_tau runs without any date in the trip
    _, trip, _ = plan_vung_tau()
    assert trip.date_from is None and trip.days
