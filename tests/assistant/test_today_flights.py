"""Today's flights that left, or leave within the lead time, are not offered (TF31)."""

import asyncio
from datetime import date, datetime, timedelta
from uuid import uuid4

import httpx

from app.services.assistant.admission import VIETNAM
from app.services.assistant.controller import DayMonth, to_understanding
from app.services.assistant.schemas import ChatRequest, TripContext, Understanding
from app.services.assistant.turn import Turn
from evals.assistant.run import controller_plan
from tests.assistant.test_report_regressions import FakeCore, FakeWeather, flight

TODAY_FLIGHTS = {
    "/api/flights": {
        "flights": [
            flight("A", "07:00", 1_000_000),
            flight("B", "09:30", 1_100_000),
            flight("C", "10:30", 1_200_000),
        ]
    }
}


def run_flights(*, now: datetime, day: date):
    out = controller_plan(intent="find_flight", from_airport="SGN", to_airport="HAN")
    out = out.model_copy(update={"start": calendar_dm(day)})
    request = ChatRequest(conversation_id=uuid4(), message="vé bay hôm nay")

    async def go():
        async with FakeCore(TODAY_FLIGHTS).client() as client:
            parsed = to_understanding(out, None, now.date())
            turn = Turn(request, parsed, core=client, weather=FakeWeather([]), now=now)
            return await turn.answer()

    return asyncio.run(go())


def calendar_dm(day: date) -> DayMonth:
    return DayMonth(day=day.day, month=day.month)


def test_today_flights_drop_departed():
    now = datetime(2026, 11, 26, 8, 0, tzinfo=VIETNAM)
    answer = run_flights(now=now, day=now.date())
    assert [c.title for c in answer.cards] == ["VN C · 10:30"]


def test_today_no_flights_left_message():
    now = datetime(2026, 11, 26, 15, 0, tzinfo=VIETNAM)
    answer = run_flights(now=now, day=now.date())
    assert answer.kind == "no_result" and not answer.cards
    assert answer.text.startswith(
        "Hôm nay không còn chuyến nào cất cánh sau 17:00 nữa, bạn xem ngày mai nha?"
    )
    assert answer.suggestions == ["Xem ngày mai", "Đổi ngày"]


def test_other_day_flights_untouched():
    now = datetime(2026, 11, 26, 15, 0, tzinfo=VIETNAM)
    answer = run_flights(now=now, day=now.date() + timedelta(days=1))
    assert [c.title for c in answer.cards] == ["VN A · 07:00", "VN B · 09:30", "VN C · 10:30"]


def test_plan_today_outbound_uses_now():
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/suggest" and request.url.params.get("types") == "airport":
            code = {"Hà Nội": "HAN", "Đà Nẵng": "DAD"}.get(request.url.params["q"])
            items = [{"type": "airport", "refId": code, "name": code}] if code else []
            return httpx.Response(200, json={"items": items})
        if path == "/api/flights":
            return httpx.Response(200, json=TODAY_FLIGHTS["/api/flights"])
        return httpx.Response(404)

    now = datetime(2026, 11, 26, 8, 0, tzinfo=VIETNAM)
    trip = TripContext(place="Đà Nẵng", date_from=now.date())
    request = ChatRequest(conversation_id=uuid4(), message="đi từ hà nội", trip=trip)
    parsed = Understanding(intent="change_transport", from_city="Hà Nội", place="Đà Nẵng")

    async def go():
        transport = httpx.MockTransport(handle)
        async with httpx.AsyncClient(base_url="https://core.test", transport=transport) as client:
            turn = Turn(request, parsed, core=client, weather=FakeWeather([]), now=now)
            return await turn.answer()

    answer = asyncio.run(go())
    assert [c.title for c in answer.cards if c.kind == "flight"] == ["VN C · 10:30"]
