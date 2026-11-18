"""A plan asks first, then fits real services and stops into one itinerary."""

import asyncio
import json
from datetime import date
from uuid import uuid4

import httpx
import pytest

from app.services.assistant.controller import apply_guards, to_understanding
from app.services.assistant.itinerary import travel_slots
from app.services.assistant.schemas import (
    Awaiting,
    ChatRequest,
    DraftAction,
    TripContext,
    Understanding,
)
from app.services.assistant.skills.plan import TripPlanner
from app.services.assistant.turn import Turn
from evals.assistant.run import CORE, FakeWeather, controller_plan

TODAY = date(2026, 11, 18)


def flight(product, depart, arrive):
    return {
        "productId": product,
        "name": f"Chuyến {product}",
        "departTime": depart,
        "arriveTime": arrive,
        "isAvailable": True,
        "priceFrom": 1,
        "fares": [{"code": "ECO", "pricePerPerson": 1, "totalPrice": 2}],
    }


def run(parsed, trip=None, *, message="...", action=None, flight_error=False, gone_return=False):
    calls = []

    def handle(request):
        path, params = request.url.path, dict(request.url.params)
        calls.append((path, params))
        if path == "/api/suggest":
            if params["types"] == "airport":
                code = {"TP.HCM": "SGN", "Hà Nội": "HAN", "Đà Lạt": "DLI"}.get(params["q"])
                return httpx.Response(
                    200, json={"items": [{"type": "airport", "refId": code}] if code else []}
                )
            return httpx.Response(200, json={"items": [{"type": "place", "refId": "dalat"}]})
        if path == "/api/stays":
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "hotelId": f"h{i}",
                            "name": f"Khách sạn {i}",
                            "unitPrice": 1,
                            "totalPrice": 2,
                        }
                        for i in (1, 2, 3)
                    ]
                },
            )
        if path.startswith("/api/hotels/"):
            return httpx.Response(
                200,
                json={
                    "name": f"Khách sạn {path[-1]}",
                    "location": {"lat": 10.01, "lng": 107.01},
                    "rooms": [{"isAvailable": True, "ratePlans": [{"totalPrice": 2}]}],
                },
            )
        if path == "/api/flights":
            if flight_error:
                return httpx.Response(503)
            offers = (
                [flight("overnight", "04:00", "06:00"), flight("out", "13:30", "14:30")]
                if params["from"] in {"SGN", "HAN"}
                else [flight("back-early", "09:00", "10:00"), flight("back", "21:00", "22:00")]
            )
            if gone_return:
                offers = [offer for offer in offers if offer["productId"] != "back"]
            return httpx.Response(200, json={"flights": offers})
        if path == "/api/places":
            return httpx.Response(200, json=CORE[path])
        return httpx.Response(404)

    async def go():
        async with httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(handle)
        ) as core:
            request = ChatRequest(
                conversation_id=uuid4(), message=message, trip=trip, action=action
            )
            turn = Turn(request, parsed, core=core, weather=FakeWeather(), today=TODAY)
            answer = await turn.answer()
            assert not turn.degraded
            return answer, turn.next_trip(answer), calls

    return asyncio.run(go())


def plan(**fields):
    return Understanding(intent="plan_trip", place="Đà Lạt", nights=2, **fields)


def full_plan():
    return run(plan(from_city="TP.HCM", check_in=date(2026, 11, 21)))


@pytest.mark.parametrize(
    ("fields", "missing"),
    [
        ({}, "origin_dates"),
        ({"from_city": "TP.HCM"}, "dates"),
        ({"check_in": date(2026, 11, 21)}, "origin"),
    ],
)
def test_plan_asks_for_missing_services_inputs_before_any_core_call(fields, missing):
    answer, trip, calls = run(plan(**fields))
    assert answer.kind == "clarify" and not answer.cards and not calls
    assert trip.awaiting == Awaiting(intent="plan_trip", missing=missing, nights=2)
    assert trip.place == "Đà Lạt" and not trip.days
    if missing == "origin_dates":
        assert (
            answer.text
            == "Bạn đi từ đâu và đi ngày nào để Tripi xếp lịch kèm vé máy bay và phòng nha?"
        )


@pytest.mark.parametrize("model_intent", ["search", "plan_trip", "change_transport", "find_flight"])
def test_city_and_date_reply_builds_woven_services(model_intent):
    _, trip, _ = run(plan())
    message = "từ Sài Gòn, 21/11"
    out = apply_guards(
        controller_plan(intent=model_intent, query=message),
        message,
        has_reel=False,
        awaiting=trip.awaiting,
    )
    assert out.intent == "plan_trip" and out.from_city == "TP.HCM"
    parsed = to_understanding(out, trip, TODAY)
    answer, trip, calls = run(parsed, trip, message=message)
    assert len(answer.cards) == 1 and answer.cards[0].kind == "itinerary"
    assert trip.origin_city == "TP.HCM" and len(trip.days) == 3
    assert trip.stay and trip.stay.id == "h1" and trip.stay.lat == 10.01
    assert trip.transport and trip.transport.flight_id == "out"
    assert trip.return_transport and trip.return_transport.flight_id == "back"
    assert len(trip.pending) == 3
    lines = answer.cards[0].lines or []
    assert lines[0].service == "flight" and "SGN → DLI 13:30–14:30" in lines[0].label
    assert lines[1].service == "stay" and "Nhận phòng" in lines[1].label
    assert lines[-2].service == "stay" and "Trả phòng" in lines[-2].label
    assert lines[-1].service == "flight" and "DLI → SGN" in lines[-1].label
    assert all(stop.slot not in {"sáng", "trưa"} for stop in trip.days[0])
    assert all("km" in line.detail and "phút" in line.detail for line in lines if not line.service)
    actions = answer.cards[0].actions
    assert actions and len(actions) == 1
    assert actions[0].params == {
        "destination": "Đà Lạt",
        "adults": "2",
        "startDate": "2026-11-21",
        "days": "3",
        "hotelId": "h1",
        "hotelName": "Khách sạn 1",
        "checkIn": "2026-11-21",
        "nights": "2",
        "flightFrom": "SGN",
        "flightTo": "DLI",
        "flightDate": "2026-11-21",
        "returnFrom": "DLI",
        "returnTo": "SGN",
        "returnDate": "2026-11-23",
    }
    assert (
        "/api/flights",
        {"from": "DLI", "to": "SGN", "date": "2026-11-23", "passengers": "2"},
    ) in calls
    facts = json.dumps(answer.facts, ensure_ascii=False)
    assert "Khách sạn 1" in facts and "Chuyến out" in facts and "Chuyến back" in facts
    assert "price" not in facts and "totalPrice" not in facts


def test_origin_then_date_fills_only_the_remaining_question():
    _, trip, _ = run(plan())
    for message, missing in [("mình đi từ Hà Nội", "dates"), ("ngày 21/11", None)]:
        out = apply_guards(
            controller_plan(intent="search", query=message),
            message,
            has_reel=False,
            awaiting=trip.awaiting,
        )
        answer, trip, _ = run(to_understanding(out, trip, TODAY), trip, message=message)
        assert trip.origin_city == "Hà Nội"
        assert (trip.awaiting.missing if trip.awaiting else None) == missing
    assert answer.cards[0].kind == "itinerary" and answer.cards[0].actions


def test_destination_reply_stays_the_destination_before_asking_origin_and_dates():
    trip = TripContext(awaiting=Awaiting(intent="plan_trip", missing="place", nights=2))
    out = apply_guards(
        controller_plan(intent="search", place="Đà Lạt"),
        "Đà Lạt",
        has_reel=False,
        awaiting=trip.awaiting,
    )
    parsed = to_understanding(out, trip, TODAY)
    answer, trip, calls = run(parsed, trip, message="Đà Lạt")
    assert answer.kind == "clarify" and trip.place == "Đà Lạt" and not trip.origin_city
    assert trip.awaiting and trip.awaiting.missing == "origin_dates" and not calls


@pytest.mark.parametrize("message", ["chưa biết", "cứ lên trước", "không biết ngày, cứ lên trước"])
def test_user_can_choose_a_bare_itinerary(message):
    _, trip, _ = run(plan())
    out = apply_guards(
        controller_plan(intent="ack"), message, has_reel=False, awaiting=trip.awaiting
    )
    answer, trip, calls = run(to_understanding(out, trip, TODAY), trip, message=message)
    assert answer.cards[0].kind == "itinerary" and not answer.cards[0].actions
    assert len(trip.days) == 3 and not trip.awaiting
    assert not any(path == "/api/flights" for path, _ in calls)


def test_flight_failure_keeps_stay_and_itinerary_without_button(caplog):
    answer, trip, _ = run(plan(from_city="TP.HCM", check_in=date(2026, 11, 21)), flight_error=True)
    assert answer.cards[0].kind == "itinerary" and trip.stay
    assert any(line.service == "stay" for line in answer.cards[0].lines or [])
    assert not answer.cards[0].actions and "flight degraded" in caplog.text


def test_no_airport_weaves_reference_bus_and_stay_without_button():
    answer, trip, _ = run(
        Understanding(
            intent="plan_trip",
            place="Vũng Tàu",
            nights=2,
            from_city="TP.HCM",
            check_in=date(2026, 11, 21),
        )
    )
    lines = answer.cards[0].lines or []
    assert trip.transport and trip.transport.mode == "bus"
    assert "Xe khách" in lines[0].label and lines[0].service is None
    assert lines[1].service == "stay" and not answer.cards[0].actions


def test_changing_stay_and_flight_rebuilds_the_same_woven_card():
    _, trip, _ = full_plan()
    answer, trip, _ = run(Understanding(intent="change_stay"), trip)
    assert answer.cards[0].kind == "compare"
    answer, trip, _ = run(None, trip, action=DraftAction(type="select", ref="o1"))
    assert answer.cards[0].kind == "itinerary"
    actions = answer.cards[0].actions
    assert actions and actions[0].params and actions[0].params["hotelId"] == "h2"
    _, trip, _ = run(Understanding(intent="change_transport"), trip)
    answer, trip, _ = run(None, trip, action=DraftAction(type="select", ref="r1"))
    assert answer.cards[0].kind == "itinerary" and answer.cards[0].actions
    assert trip.transport and trip.transport.flight_id == "overnight"
    assert any(stop.slot == "sáng" for stop in trip.days[0])


@pytest.mark.parametrize("gone_return", [False, True])
def test_confirm_rechecks_the_return_fare(gone_return):
    _, trip, _ = full_plan()
    answer, _, calls = run(Understanding(intent="confirm_booking"), trip, gone_return=gone_return)
    actions = answer.cards[0].actions
    assert actions and actions[0].params
    params = actions[0].params
    assert ("returnDate" in params) is not gone_return
    assert any(path == "/api/flights" and q["from"] == "DLI" for path, q in calls)
    if gone_return:
        assert "Chuyến về" in answer.text


@pytest.mark.parametrize(
    ("arrival", "departure", "slots"),
    [
        ("14:30", None, {"chiều", "tối"}),
        ("17:00", None, {"tối"}),
        (None, "17:00", {"sáng", "trưa", "chiều"}),
        (None, "11:00", {"sáng"}),
    ],
)
def test_travel_windows_keep_stops_clear_of_flights(arrival, departure, slots):
    assert travel_slots(arrival=arrival, departure=departure) == slots


def test_old_trip_json_without_service_fields_still_parses():
    trip = TripContext.model_validate(
        {"place": "Đà Lạt", "transport": {"mode": "flight", "summary": "VN"}}
    )
    assert trip.return_transport is None and trip.transport and trip.transport.arrive_time is None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("ngày mai", date(2026, 11, 19)),
        ("cuối tuần này", date(2026, 11, 21)),
        ("t7", date(2026, 11, 21)),
        ("chủ nhật", date(2026, 11, 22)),
    ],
)
def test_relative_date_reply_does_not_need_a_model_slot(message, expected):
    _, trip, _ = run(plan(from_city="TP.HCM"))
    out = apply_guards(
        controller_plan(intent="search", query=message),
        message,
        has_reel=False,
        awaiting=trip.awaiting,
    )
    parsed = to_understanding(out, trip, TODAY)
    answer, trip, _ = run(parsed, trip, message=message)
    assert answer.cards[0].kind == "itinerary" and trip.date_from == expected


def test_points_weather_stays_and_both_flights_start_concurrently(monkeypatch):
    ready = asyncio.Event()
    count = 0

    def wrapped(method):
        async def wait_together(self, *args, **kwargs):
            nonlocal count
            count += 1
            if count == 5:
                ready.set()
            await ready.wait()
            return await method(self, *args, **kwargs)

        return wait_together

    for name in ["_plan_points", "_rain_capped", "_plan_stays", "_plan_flight"]:
        monkeypatch.setattr(TripPlanner, name, wrapped(getattr(TripPlanner, name)))
    answer, _, _ = full_plan()
    assert count == 5 and answer.cards[0].actions


@pytest.mark.parametrize(
    "message",
    ["mình đi từ Sài Gòn, ngày 21/11", "từ Sài Gòn", "đi từ Sài Gòn ngày 21/11 nha"],
)
def test_a_longer_origin_and_day_reply_finishes_the_plan(message):
    # 7 words were over the short-reply limit: the model left from_city empty and Tripi asked again.
    out = apply_guards(
        controller_plan(
            intent="plan_trip", place="Đà Lạt", start={"day": 21, "month": 11, "year": None}
        ),
        message,
        has_reel=False,
        awaiting=Awaiting(intent="plan_trip", missing="origin_dates", nights=2),
    )
    assert (out.intent, out.from_city) == ("plan_trip", "TP.HCM")


def test_city_aliases_and_a_copied_end_day_do_not_break_the_plan():
    out = apply_guards(
        controller_plan(intent="plan_trip", place="Đà Lạt", from_city="Sài Gòn"),
        "mình đi từ Sài Gòn, ngày 21/11",
        has_reel=False,
    )
    assert out.from_city == "TP.HCM"  # the fake and the real core both know this name
    copied = controller_plan(
        intent="plan_trip",
        place="Vũng Tàu",
        nights=2,
        start={"day": 21, "month": 11, "year": None},
        end={"day": 21, "month": 11, "year": None},
    )
    parsed = to_understanding(copied, None, date(2026, 11, 18))
    assert (parsed.check_in, parsed.check_out) == (date(2026, 11, 21), None)
