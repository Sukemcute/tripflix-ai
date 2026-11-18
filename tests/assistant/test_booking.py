"""Booking buttons use fresh Core availability, never LLM-made IDs or paths."""

import asyncio
import json
from copy import deepcopy
from datetime import date
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.clients.llm.base import LlmResult
from app.clients.places import CorePlaces
from app.services.assistant import understand
from app.services.assistant.controller import apply_guards, to_understanding
from app.services.assistant.schemas import (
    CardAction,
    ChatRequest,
    DraftAction,
    TripContext,
    Understanding,
)
from app.services.assistant.skills.flight import search_flights
from app.services.assistant.skills.plan import REVIEW_CHIPS, TripPlanner
from app.services.assistant.turn import Turn
from evals.assistant.run import CORE, TODAY, FakeWeather, controller_plan, fake_core


def chosen_trip() -> TripContext:
    return TripContext.model_validate(
        {
            "place": "Đà Nẵng",
            "dateFrom": "2026-11-21",
            "dateTo": "2026-11-23",
            "originCity": "TP.HCM",
            "adults": 2,
            "stay": {"source": "tripflix", "id": "h1", "name": "Khách sạn"},
            "transport": {
                "mode": "flight",
                "summary": "VN 8 · 08:30",
                "flightId": "f8",
                "fareCode": "ECO",
                "flightDate": "2026-11-21",
                "fromAirport": "SGN",
                "toAirport": "DAD",
                "passengers": 2,
            },
        }
    )


def run_turn(trip, parsed, action=None, *, message="..."):
    calls = []

    async def run():
        async with fake_core(calls) as core:
            request = ChatRequest(
                conversation_id=uuid4(), message=message, trip=trip, action=action
            )
            turn = Turn(request, parsed, core=core, weather=FakeWeather(), today=TODAY)
            answer = await turn.answer()
            assert not turn.degraded
            return answer, turn.next_trip(answer), calls

    return asyncio.run(run())


def test_confirm_rechecks_both_parts_and_returns_exact_booking_routes(monkeypatch):
    flights = deepcopy(CORE["/api/flights"])
    for offer in flights["flights"]:
        if offer["productId"] == "f8":
            offer.update(name="Bay TP.HCM – Đà Nẵng 11:00", departTime="11:00")
    monkeypatch.setitem(CORE, "/api/flights", flights)
    answer, _, calls = run_turn(chosen_trip(), Understanding(intent="confirm_booking"))
    assert answer.kind == "answer"
    card = answer.cards[0]
    assert card.kind == "booking" and len(card.lines or []) == 2
    assert card.lines and card.lines[1].label == "Bay TP.HCM – Đà Nẵng 11:00"
    assert card.lines[1].label.count("11:00") == 1
    assert [a.model_dump(exclude_none=True) for a in card.actions or []] == [
        {
            "type": "book",
            "label": "Đặt theo lộ trình",
            "path": "/trip-builder",
            "params": {
                "destination": "Đà Nẵng",
                "adults": "2",
                "startDate": "2026-11-21",
                "hotelId": "h1",
                "hotelName": "Vinpearl Beach Nha Trang",
                "checkIn": "2026-11-21",
                "nights": "2",
                "flightFrom": "SGN",
                "flightTo": "DAD",
                "flightDate": "2026-11-21",
            },
        },
    ]
    assert calls == [
        ("/api/hotels/h1", {"checkIn": "2026-11-21", "checkOut": "2026-11-23", "adults": "2"}),
        ("/api/flights", {"from": "SGN", "to": "DAD", "date": "2026-11-21", "passengers": "2"}),
    ]
    assert "price" not in json.dumps(answer.facts).lower()


@pytest.mark.parametrize("hotel", [None, {"name": "Khách sạn", "rooms": []}])
def test_confirm_sold_out_or_removed_stay_seeds_only_the_flight(monkeypatch, hotel):
    monkeypatch.setitem(CORE, "/api/hotels/", hotel)
    answer, _, _ = run_turn(chosen_trip(), Understanding(intent="confirm_booking"))
    assert (card_actions := answer.cards[0].actions)
    assert len(card_actions) == 1 and card_actions[0].path == "/trip-builder"
    assert card_actions[0].params == {
        "destination": "Đà Nẵng",
        "adults": "2",
        "startDate": "2026-11-21",
        "flightFrom": "SGN",
        "flightTo": "DAD",
        "flightDate": "2026-11-21",
    }
    assert "hết phòng" in answer.text and "đổi chỗ ở" in answer.text


@pytest.mark.parametrize("change", ["fare", "flight", "sold_out"])
def test_confirm_missing_fare_or_flight_seeds_only_the_stay(monkeypatch, change):
    flights = deepcopy(CORE["/api/flights"])
    for offer in flights["flights"]:
        if offer["productId"] == "f8":
            if change == "fare":
                offer["fares"] = [{"code": "BUS", "pricePerPerson": 5, "totalPrice": 10}]
            elif change == "flight":
                offer["productId"] = "other"
            else:
                offer["isAvailable"] = False
    monkeypatch.setitem(CORE, "/api/flights", flights)
    answer, _, _ = run_turn(chosen_trip(), Understanding(intent="confirm_booking"))
    assert (card_actions := answer.cards[0].actions)
    assert len(card_actions) == 1 and card_actions[0].path == "/trip-builder"
    assert card_actions[0].params == {
        "destination": "Đà Nẵng",
        "adults": "2",
        "startDate": "2026-11-21",
        "hotelId": "h1",
        "hotelName": "Vinpearl Beach Nha Trang",
        "checkIn": "2026-11-21",
        "nights": "2",
    }
    assert "không còn chỗ" in answer.text and "đổi chuyến bay" in answer.text


def test_confirm_nothing_selected_clarifies_without_calling_core():
    answer, _, calls = run_turn(TripContext(), Understanding(intent="confirm_booking"))
    assert answer.kind == "clarify" and not answer.cards and not calls
    assert answer.suggestions == ["Đổi chỗ ở", "Đổi chuyến bay"]


def test_old_transport_json_still_parses():
    trip = TripContext.model_validate_json(
        '{"v":2,"place":"Đà Nẵng","transport":{"mode":"flight","summary":"Bay tới DAD"}}'
    )
    assert trip.transport and trip.transport.flight_id is None
    assert trip.transport.fare_code is None and trip.pending_flights == []


@pytest.mark.parametrize(
    "path",
    ["/checkout", "https://evil.test", "//evil.test", "/flights/evil", "/hotel-rooms", "/flights"],
)
def test_card_action_rejects_other_paths(path):
    with pytest.raises(ValidationError):
        CardAction.model_validate({"type": "book", "label": "Đặt", "path": path, "params": {}})


@pytest.mark.parametrize(
    "action",
    [
        {"type": "select", "label": "Chọn"},
        {"type": "book", "label": "Đặt", "params": {}},
        {"type": "book", "label": "Đặt", "path": "/trip-builder"},
        {"type": "select", "label": "Chọn", "ref": "r1", "path": "/trip-builder"},
        {"type": "select", "label": "x" * 41, "ref": "r1"},
    ],
)
def test_card_action_requires_the_correct_target(action):
    with pytest.raises(ValidationError):
        CardAction.model_validate(action)


@pytest.mark.parametrize("ordinal", [False, True])
def test_select_flight_remembers_fields_and_keeps_pending_stays(ordinal):
    trip = chosen_trip()
    assert trip.transport
    trip.pending_flights = [trip.transport.model_copy(update={"ref": "r1"})]
    trip.transport = None
    parsed = Understanding(intent="select_option", card_ordinal=1) if ordinal else None
    action = None if ordinal else DraftAction(type="select", ref="r1")
    answer, memory, calls = run_turn(trip, parsed, action)
    assert memory.transport and memory.transport.flight_id == "f8"
    assert memory.transport.flight_date == date(2026, 11, 21)
    assert memory.transport.fare_code == "ECO" and memory.pending_flights == []
    assert answer.suggestions == REVIEW_CHIPS and "hay chốt luôn" in (answer.lead or "")
    assert not calls


def test_plan_then_select_flight_and_stay_then_confirm():
    plan = Understanding(
        intent="plan_trip", place="Đà Nẵng", day_ref="this_weekend", nights=2, from_city="TP.HCM"
    )
    answer, memory, _ = run_turn(TripContext(), plan)
    assert [c.kind for c in answer.cards] == ["itinerary"]
    assert len(memory.days) == 3 and memory.pending
    assert answer.cards[0].actions and answer.cards[0].actions[0].type == "book"
    answer, memory, _ = run_turn(
        memory, Understanding(intent="change_transport", from_city="TP.HCM")
    )
    assert all(c.kind == "flight" and c.actions for c in answer.cards)
    assert memory.transport and memory.pending
    _, memory, _ = run_turn(memory, None, DraftAction(type="select", ref="r2"))
    _, memory, _ = run_turn(memory, None, DraftAction(type="select", ref="o1"))
    assert memory.stay and memory.transport
    answer, _, _ = run_turn(memory, Understanding(intent="confirm_booking"))
    assert [a.path for a in answer.cards[0].actions or []] == ["/trip-builder"]
    assert (actions := answer.cards[0].actions) and actions[0].params
    assert actions[0].params["days"] == "3"


def test_confirm_no_availability_has_no_booking_button(monkeypatch):
    monkeypatch.setitem(CORE, "/api/hotels/", {"rooms": []})
    monkeypatch.setitem(CORE, "/api/flights", {"flights": []})
    answer, _, _ = run_turn(chosen_trip(), Understanding(intent="confirm_booking"))
    assert answer.kind == "no_result" and answer.cards[0].actions == []


def test_confirm_flight_only_uses_flight_date_for_builder_start():
    trip = chosen_trip()
    trip.stay, trip.date_from, trip.date_to = None, None, None
    answer, _, _ = run_turn(trip, Understanding(intent="confirm_booking"))
    assert (action := answer.cards[0].actions)
    assert action[0].params and action[0].params["startDate"] == "2026-11-21"
    assert "hotelId" not in action[0].params and "days" not in action[0].params


@pytest.mark.parametrize(
    "reply_intent", ["plan_trip", "search", "clarify", "find_stay", "find_reel", "find_flight"]
)
@pytest.mark.parametrize("has_model_date", [False, True])
def test_transport_date_reply_finishes_the_undated_plan(reply_intent, has_model_date):
    answer, memory, _ = run_turn(
        TripContext(),
        Understanding(
            intent="plan_trip",
            place="Đà Nẵng",
            nights=2,
        ),
        message="Tôi muốn đi Đà Nẵng 3n2d, lên lộ trình chi tiết cho tôi",
    )
    assert answer.kind == "clarify" and memory.date_from is None
    answer, memory, _ = run_turn(
        memory,
        Understanding(
            intent="change_transport",
            from_city="TP.HCM",
        ),
        message="Bay từ TP.HCM",
    )
    assert answer.kind == "clarify" and "bay ngày nào" in answer.text
    assert memory.awaiting and memory.awaiting.intent == "change_transport"
    assert memory.awaiting.missing == "dates" and memory.origin_city == "TP.HCM"
    out = apply_guards(
        controller_plan(
            intent=reply_intent,
            query="ngày 20/11",
            start={"day": 20, "month": 11} if has_model_date else None,
            place="Đà Nẵng",
        ),
        "ngày 20/11",
        has_reel=False,
        in_plan=True,
        awaiting=memory.awaiting,
    )
    assert out.intent == "change_transport"
    parsed = to_understanding(out, memory, TODAY)
    answer, memory, calls = run_turn(memory, parsed, message="ngày 20/11")
    assert answer.cards and all(c.kind == "flight" for c in answer.cards)
    assert all(c.actions and c.actions[0].label == "Chọn chuyến này" for c in answer.cards)
    assert (
        "/api/flights",
        {"from": "SGN", "to": "DAD", "date": "2026-11-20", "passengers": "2"},
    ) in calls
    assert memory.date_from == date(2026, 11, 20) and memory.awaiting is None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("ngày 20/11", date(2026, 11, 20)),
        ("ngày 20/11/2026", date(2026, 11, 20)),
        ("ngày 20/11/2027", date(2027, 11, 20)),
        ("ngày 17/11", date(2027, 11, 17)),
        ("ngày 18/11", date(2026, 11, 18)),
        ("ngày 29/02", date(2028, 2, 29)),
        ("ngày 31/02", None),
        ("ngày 29/02/2027", None),
    ],
)
def test_awaiting_transport_date_reads_message_when_model_only_fills_query(message, expected):
    trip = TripContext.model_validate(
        {"awaiting": {"intent": "change_transport", "missing": "dates"}}
    )
    out = apply_guards(
        controller_plan(intent="search", query=message),
        message,
        has_reel=False,
        awaiting=trip.awaiting,
    )
    assert out.intent == "change_transport"
    parsed = to_understanding(out, trip, date(2026, 11, 18))
    assert parsed.flight_date == expected and parsed.check_in == expected


def test_awaiting_transport_date_counts_date_words_without_model_slots():
    trip = TripContext.model_validate(
        {"awaiting": {"intent": "change_transport", "missing": "dates"}}
    )
    out = apply_guards(
        controller_plan(intent="search", query="ngày mai"),
        "ngày mai",
        has_reel=False,
        awaiting=trip.awaiting,
    )
    assert out.intent == "change_transport"


@pytest.mark.parametrize(
    "reply_intent", ["search", "clarify", "find_stay", "find_reel", "find_flight"]
)
def test_transport_origin_reply_keeps_the_destination_and_finishes_the_question(reply_intent):
    answer, memory, _ = run_turn(
        TripContext(
            place="Đà Nẵng",
            date_from=date(2026, 11, 20),
        ),
        Understanding(intent="change_transport"),
    )
    assert answer.kind == "clarify" and memory.awaiting
    assert memory.awaiting.intent == "change_transport" and memory.awaiting.missing == "origin"
    out = apply_guards(
        controller_plan(intent=reply_intent, place="Hà Nội", missing="origin"),
        "từ Hà Nội",
        has_reel=False,
        awaiting=memory.awaiting,
    )
    assert out.intent == "change_transport" and out.from_city == "Hà Nội"
    parsed = to_understanding(out, memory, TODAY)
    answer, memory, calls = run_turn(memory, parsed, message="từ Hà Nội")
    assert answer.cards and all(c.kind == "flight" for c in answer.cards)
    assert (
        "/api/flights",
        {"from": "HAN", "to": "DAD", "date": "2026-11-20", "passengers": "2"},
    ) in calls
    assert memory.origin_city == "Hà Nội" and memory.place == "Đà Nẵng"
    assert memory.awaiting is None


@pytest.mark.parametrize(
    ("name", "title"),
    [
        ("Bay TP.HCM – Đà Nẵng 11:00", "Bay TP.HCM – Đà Nẵng 11:00"),
        ("Bay TP.HCM – Đà Nẵng", "Bay TP.HCM – Đà Nẵng · 11:00"),
    ],
)
def test_flight_title_only_appends_departure_time_when_missing(monkeypatch, name, title):
    offer = deepcopy(CORE["/api/flights"]["flights"][0])
    offer.update(name=name, departTime="11:00")
    monkeypatch.setitem(CORE, "/api/flights", {"flights": [offer]})
    answer, _, _ = run_turn(
        TripContext(),
        Understanding(
            intent="find_flight",
            from_airport="SGN",
            to_airport="DAD",
            flight_date=date(2026, 11, 21),
        ),
    )
    assert answer.cards[0].title == title


@pytest.mark.parametrize(
    ("origins", "destinations", "routes", "status", "kind", "codes"),
    [
        (["SGN", "VCS"], ["DAD"], [("SGN", "DAD")], 200, "answer", ["SGN", "DAD"]),
        (["SGN", "VCS"], ["DAD"], [("SGN", "DAD"), ("VCS", "DAD")], 200, "clarify", ["SGN", "VCS"]),
        (["SGN", "VCS"], ["DAD"], [], 200, "no_result", []),
        (["SGN", "VCS"], ["DAD"], [], 503, "clarify", ["SGN", "VCS"]),
        (["SGN", "VCS"], ["DAD", "VDO"], [("SGN", "DAD")], 200, "answer", ["SGN", "DAD"]),
        (["SGN"], ["DAD", "VDO"], [("SGN", "DAD")], 200, "answer", ["SGN", "DAD"]),
        (
            ["SGN", "VCS"],
            ["DAD", "VDO", "DIN"],
            [("SGN", "DAD"), ("SGN", "VDO")],
            200,
            "clarify",
            ["DAD", "VDO"],
        ),
    ],
)
def test_ambiguous_airports_only_offer_connected_pairs(
    origins, destinations, routes, status, kind, codes, caplog
):
    calls = []

    def handle(request):
        calls.append(request)
        if request.url.path == "/api/suggest":
            airports = origins if request.url.params["q"] == "Sài Gòn" else destinations
            return httpx.Response(
                200,
                json={
                    "items": [
                        {"type": "airport", "refId": code, "name": f"Sân bay {code}"}
                        for code in airports
                    ]
                },
            )
        if request.url.path == "/api/flights/routes":
            return httpx.Response(
                status,
                json=[
                    {"fromAirport": start, "toAirport": end, "flightCount": 1}
                    for start, end in routes
                ],
            )
        assert request.url.path == "/api/flights"
        return httpx.Response(200, json=CORE["/api/flights"])

    async def run():
        async with httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(handle)
        ) as core:
            return await search_flights(
                core,
                Understanding(
                    intent="find_flight",
                    from_city="Sài Gòn",
                    to_city="Đà Nẵng",
                    flight_date=date(2026, 11, 21),
                ),
            )

    answer = asyncio.run(run())
    assert answer.kind == kind
    assert sum(r.url.path == "/api/flights/routes" for r in calls) == 1
    searches = [r for r in calls if r.url.path == "/api/flights"]
    if kind == "answer":
        assert len(searches) == 1
        assert [searches[0].url.params["from"], searches[0].url.params["to"]] == codes
        assert answer.cards[0].from_airport == codes[0]
    else:
        assert not searches
        assert all(code in answer.text for code in codes)
        if kind == "no_result":
            assert "chưa có tuyến bay Sài Gòn – Đà Nẵng" in answer.text
            assert "hết chỗ" not in answer.text
        if codes == ["DAD", "VDO"]:
            assert "DIN" not in answer.text
    if status != 200:
        assert "flight routes degraded" in caplog.text


def test_explicit_airport_codes_are_not_replaced_or_checked_against_routes():
    calls = []

    def handle(request):
        calls.append(request)
        assert request.url.path == "/api/flights"
        return httpx.Response(200, json=CORE["/api/flights"])

    async def run():
        async with httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(handle)
        ) as core:
            return await search_flights(
                core,
                Understanding(
                    intent="find_flight",
                    from_city="Sài Gòn",
                    from_airport="VCS",
                    to_airport="DAD",
                    flight_date=date(2026, 11, 21),
                ),
            )

    answer = asyncio.run(run())
    assert answer.kind == "answer" and len(calls) == 1
    assert calls[0].url.params["from"] == "VCS"


def test_transport_date_reply_also_resolves_relative_days():
    trip = TripContext.model_validate(
        {
            "place": "Đà Nẵng",
            "originCity": "TP.HCM",
            "awaiting": {"intent": "change_transport", "missing": "dates"},
        }
    )
    out = apply_guards(
        controller_plan(intent="search", day_ref="tomorrow"),
        "ngày mai",
        has_reel=False,
        awaiting=trip.awaiting,
    )
    parsed = to_understanding(out, trip, TODAY)
    answer, memory, calls = run_turn(trip, parsed, message="ngày mai")
    assert answer.cards and answer.cards[0].flight_date == date(2026, 11, 17)
    assert (
        "/api/flights",
        {"from": "SGN", "to": "DAD", "date": "2026-11-17", "passengers": "2"},
    ) in calls
    assert memory.awaiting is None


def test_direct_flight_search_also_remembers_selectable_options():
    answer, memory, _ = run_turn(
        TripContext(),
        Understanding(
            intent="find_flight",
            from_airport="SGN",
            to_airport="DAD",
            flight_date=date(2026, 11, 21),
            check_in=date(2026, 11, 21),
        ),
    )
    assert answer.cards and memory.pending_flights
    _, memory, _ = run_turn(memory, None, DraftAction(type="select", ref="r2"))
    assert memory.transport and memory.transport.flight_id == "f8"


def test_plan_stay_failure_keeps_itinerary_and_logs_degraded(monkeypatch, caplog):
    async def fail(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(TripPlanner, "stay_options", fail)
    answer, memory, _ = run_turn(
        TripContext(),
        Understanding(
            intent="plan_trip",
            place="Đà Nẵng",
            day_ref="this_weekend",
            nights=2,
            from_city="TP.HCM",
        ),
    )
    assert answer.cards[0].kind == "itinerary" and memory.days
    assert "stay degraded" in caplog.text
    assert memory.stay is None and not answer.cards[0].actions


def test_plan_build_and_stays_run_concurrently(monkeypatch):
    original = TripPlanner._plan_points

    async def run():
        build_started, stays_started = asyncio.Event(), asyncio.Event()

        async def build(self, *args, **kwargs):
            build_started.set()
            await stays_started.wait()
            return await original(self, *args, **kwargs)

        async def stays(self, *args, **kwargs):
            stays_started.set()
            await build_started.wait()
            return None

        monkeypatch.setattr(TripPlanner, "_plan_points", build)
        monkeypatch.setattr(TripPlanner, "_plan_stays", stays)
        async with fake_core() as core:
            planner = TripPlanner(core, CorePlaces(core), FakeWeather(), TODAY, TripContext())
            return await asyncio.wait_for(
                planner.plan(
                    Understanding(
                        intent="plan_trip",
                        place="Đà Nẵng",
                        nights=2,
                        from_city="TP.HCM",
                        day_ref="this_weekend",
                    )
                ),
                timeout=1,
            )

    assert asyncio.run(run()).kind == "answer"


def test_no_route_is_distinct_from_full_flights_with_bounded_nearby_dates():
    async def run(has_route):
        dates = []

        def handle(request):
            dates.append(request.url.params["date"])
            offers = deepcopy(CORE["/api/flights"]["flights"]) if has_route else []
            for offer in offers:
                offer["isAvailable"] = request.url.params["date"] != "2026-11-21"
            return httpx.Response(200, json={"flights": offers})

        async with httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(handle)
        ) as core:
            answer = await search_flights(
                core,
                Understanding(
                    intent="find_flight",
                    from_airport="SGN",
                    to_airport="DAD",
                    flight_date=date(2026, 11, 21),
                ),
            )
        return answer, dates

    missing, dates = asyncio.run(run(False))
    assert "chưa có tuyến" in missing.text and len(dates) == 1
    full, dates = asyncio.run(run(True))
    assert "hết chỗ" in full.text and "20/11" in full.text and len(full.suggestions) == 3
    assert len(dates) == 7 and all(18 <= date.fromisoformat(day).day <= 24 for day in dates)


@pytest.mark.parametrize(
    "message",
    [
        "chốt",
        "chot",
        "chốt và đặt",
        "chốt luôn",
        "đặt luôn",
        "dat di",
        "book di",
        "book lun",
        "ok book đi",
        "ok chốt",
        "mình chốt vậy",
        "chốt vậy nhé",
    ],
)
@pytest.mark.parametrize("model_intent", ["ack", "confirm_booking", "find_flight"])
@pytest.mark.parametrize("has_booking", [False, True])
def test_closing_phrase_uses_chosen_booking_regardless_of_model(message, model_intent, has_booking):
    out = apply_guards(
        controller_plan(intent=model_intent), message, has_reel=False, has_booking=has_booking
    )
    assert out.intent == ("confirm_booking" if has_booking else "ack")


@pytest.mark.parametrize(
    ("message", "ordinal", "flight_id"),
    [
        ("chọn khách sạn đầu tiên", 1, None),
        ("chọn chuyến 2", 2, "f8"),
        ("chọn cái đầu", 1, "f6"),
    ],
)
def test_typed_selection_uses_the_named_list_when_both_are_pending(message, ordinal, flight_id):
    _, memory, _ = run_turn(
        TripContext(),
        Understanding(
            intent="plan_trip",
            place="Đà Nẵng",
            day_ref="this_weekend",
            nights=2,
            from_city="TP.HCM",
        ),
    )
    _, memory, _ = run_turn(memory, Understanding(intent="change_transport", from_city="TP.HCM"))
    assert memory.pending and memory.pending_flights
    memory.stay, memory.transport = None, None
    answer, memory, _ = run_turn(
        memory,
        Understanding(
            intent="select_option",
            card_ordinal=ordinal,
        ),
        message=message,
    )
    assert answer.kind == "answer"
    if flight_id:
        assert memory.transport and memory.transport.flight_id == flight_id
        assert memory.stay is None
    else:
        assert memory.stay and memory.stay.id == "h1"
        assert memory.transport is None


@pytest.mark.parametrize("has_booking", [False, True])
def test_checklist_ack_only_confirms_when_something_was_chosen(has_booking):
    out = apply_guards(
        controller_plan(intent="confirm_booking"),
        "mình chốt vậy",
        has_reel=False,
        has_booking=has_booking,
    )
    assert out.intent == ("confirm_booking" if has_booking else "ack")


@pytest.mark.parametrize(
    ("message", "fields", "intent"),
    [
        (
            "ve khu hoi da nang cho 2 nguoi lon 1 em be",
            {"to_city": "Đà Nẵng", "adults": 2, "infants": 1, "round_trip": True},
            "find_flight",
        ),
        ("tìm phòng Đà Nẵng 21/11", {"place": "Đà Nẵng"}, "find_stay"),
        ("tìm phòng cho 2 người", {}, "find_stay"),
        ("đặt phòng thứ bảy", {}, "find_stay"),
        ("Đà Nẵng", {"place": "Đà Nẵng"}, "find_stay"),
        ("21/11", {}, "find_stay"),
        ("đặt luôn vé Đà Nẵng", {"to_city": "Đà Nẵng"}, "find_flight"),
        ("chốt phòng Đà Nẵng 21/11", {"place": "Đà Nẵng"}, "find_stay"),
    ],
)
def test_confirm_without_a_choice_routes_targeted_requests_to_search(message, fields, intent):
    out = apply_guards(
        controller_plan(intent="confirm_booking", **fields),
        message,
        has_reel=False,
        has_booking=False,
    )
    assert out.intent == intent
    if fields.get("round_trip"):
        assert out.round_trip and out.adults == 2 and out.infants == 1


@pytest.mark.parametrize(
    ("trip", "intent"),
    [
        (None, "ack"),
        ({"stay": {"source": "tripflix", "id": "h1", "name": "Khách sạn"}}, "confirm_booking"),
        ({"stay": {"source": "external", "id": "osm:1", "name": "Nhà nghỉ"}}, "ack"),
        ({"transport": {"mode": "flight", "summary": "Bay", "flightId": "f8"}}, "confirm_booking"),
        ({"transport": {"mode": "flight", "summary": "Bay"}}, "ack"),
    ],
)
@pytest.mark.parametrize("model_intent", ["ack", "confirm_booking"])
def test_understand_passes_only_chosen_bookable_parts_to_ack_guard(
    monkeypatch, trip, intent, model_intent
):
    class FakeController:
        async def agenerate(self, *args):
            return LlmResult(
                output=controller_plan(intent=model_intent).model_dump_json(),
                model_name="fake",
                input_tokens=0,
                output_tokens=0,
            )

    monkeypatch.setattr(understand, "get_role_llm", lambda role: FakeController())
    request = ChatRequest.model_validate(
        {
            "conversationId": str(uuid4()),
            "message": "chot",
            "trip": trip,
        }
    )
    parsed, _ = asyncio.run(understand.understand(request, max_turns=6))
    assert parsed.intent == intent
