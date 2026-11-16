"""Tripi v3 two agents: planner rules, Skills, Verifier and Responder (TF31)."""

import asyncio
import json
from datetime import date
from uuid import uuid4

import httpx
import pytest

from app.clients.llm.base import LlmResult
from app.clients.weather import DayWeather, Place, describe_sky
from app.services.assistant import planner, responder
from app.services.assistant.schemas import Answer, Card, ChatRequest, Turn, Understanding
from app.services.assistant.skills import trip
from app.services.assistant.skills import weather as weather_skill
from app.services.assistant.turn import Turn as ChatTurn
from app.services.assistant.verifier import verify

MONDAY = date(2026, 11, 16)
SUNDAY = date(2026, 11, 22)


def u(**fields) -> Understanding:
    return Understanding.model_validate({"intent": "find_stay"} | fields)


# ---- planner: relative days in Vietnam time, never computed by the LLM


@pytest.mark.parametrize(
    ("ref", "today", "expected"),
    [
        ("today", MONDAY, MONDAY),
        ("tomorrow", MONDAY, date(2026, 11, 17)),
        ("saturday", MONDAY, date(2026, 11, 21)),
        ("this_weekend", MONDAY, date(2026, 11, 21)),
        ("this_weekend", SUNDAY, SUNDAY),
        ("sunday", MONDAY, SUNDAY),
        ("next_weekend", MONDAY, date(2026, 11, 28)),
        ("none", MONDAY, None),
    ],
)
def test_relative_days(ref, today, expected):
    assert planner.start_day(u(day_ref=ref), today) == expected


def test_stay_dates_use_nights_and_explicit_dates_win():
    assert planner.stay_dates(u(day_ref="saturday", nights=2), MONDAY) == (
        date(2026, 11, 21),
        date(2026, 11, 23),
    )
    explicit = u(day_ref="saturday", check_in=date(2026, 12, 1), check_out=date(2026, 12, 3))
    assert planner.stay_dates(explicit, MONDAY) == (date(2026, 12, 1), date(2026, 12, 3))


def test_weather_days_default_to_the_next_three_and_say_so():
    assert planner.trip_days(u(), MONDAY) == (MONDAY, date(2026, 11, 18), True)


def test_one_clarifying_question_per_conversation():
    request = ChatRequest(conversation_id=uuid4(), message="ks da lat")
    assert not planner.has_asked_before(request)
    request.history = [Turn(role="assistant", text="Bạn đi ngày nào?", kind="clarify")]
    assert planner.has_asked_before(request)


# ---- Verifier: each sentence must stand on this turn's facts

FACTS = [{"ref": "r1", "kind": "weather", "place": "Vũng Tàu", "days": [{"minC": 26, "maxC": 31}]}]


@pytest.mark.parametrize(
    ("sentence", "rule"),
    [
        ("Xem [r9] nha.", "V1_unknown_ref"),
        ("Phòng chỉ 450 nghìn thôi nè.", "V2_ungrounded_number"),
        ("Ghé thêm Mũi Nghinh Phong cho đẹp nha.", "V3_ungrounded_name"),
        ("Nhanh tay kẻo hết nha bạn ơi.", "V4_scarcity"),
        ("Xem thêm ở www.abc.vn nha.", "V6_contact"),
        ("See you there!", "V7_language"),
    ],
)
def test_verifier_drops_ungrounded_sentences(sentence, rule):
    kept, dropped = verify([sentence], FACTS, {"r1"}, "thoi tiet vung tau")
    assert kept == []
    assert dropped[rule] == 1


def test_verifier_keeps_grounded_sentences_and_caps_emoji():
    sentences = [
        "Vũng Tàu khoảng 26–31°C nè ☀️🌊",
        "Chi tiết ở [r1] nha 😎",
        "Thứ Bảy nhớ mang áo mưa nha.",
    ]
    kept, dropped = verify(sentences, FACTS, {"r1"}, "thoi tiet vung tau")
    assert kept == [sentences[0], sentences[2]]
    assert dropped["V7_emoji"] == 1


def test_verifier_checks_availability_against_facts():
    facts = [{"ref": "r1", "kind": "stay", "available": False}]
    kept, dropped = verify(["Khách sạn vẫn còn phòng nha."], facts, {"r1"}, "con phong k")
    assert kept == [] and dropped["V5_availability"] == 1


# ---- Skills

DAYS = [DayWeather(date(2026, 11, 21), 26, 33, 70, describe_sky(80))]


VUNG_TAU = Place("Vũng Tàu", 10.3, 107.0)


class FakeWeather:
    def __init__(self, days=DAYS, place=VUNG_TAU):
        self.days, self.place = days, place

    async def find_place(self, name):
        return self.place

    async def forecast(self, place, start, end):
        return [d for d in self.days if start <= d.day <= end]


def test_weather_card_carries_numbers_and_attribution():
    answer, days = asyncio.run(
        weather_skill.weather(
            FakeWeather(), "Vũng Tàu", date(2026, 11, 21), date(2026, 11, 22), is_assumed=False
        )
    )
    card = answer.cards[0]
    assert (card.kind, card.source) == ("weather", "Open-Meteo.com")
    assert card.lines and card.lines[0].detail == "26–33°C, mưa rào, mưa 70%"
    assert answer.facts[0]["days"][0]["rainChance"] == 70


def test_weather_beyond_the_forecast_is_said_not_guessed():
    answer, _ = asyncio.run(
        weather_skill.weather(FakeWeather(days=[]), "Vũng Tàu", MONDAY, MONDAY, is_assumed=False)
    )
    assert answer.kind == "no_result" and answer.cards == []


def test_packing_list_follows_place_and_weather():
    items = weather_skill.packing_list("Vũng Tàu muốn đi biển", DAYS, nights=1)
    assert "Kem chống nắng" in items  # beach
    assert "Áo mưa mỏng hoặc ô" in items  # 70% rain
    assert "Bình nước" in items  # 33 °C
    assert "Áo khoác" not in items


def core_with(routes: dict[str, httpx.Response]) -> httpx.AsyncClient:
    def handle(request: httpx.Request) -> httpx.Response:
        for prefix, response in routes.items():
            if request.url.path.startswith(prefix):
                return response
        return httpx.Response(404)

    return httpx.AsyncClient(base_url="https://core.test", transport=httpx.MockTransport(handle))


POST = {
    "post": {
        "id": "p1",
        "authorId": "a1",
        "title": "Phú Quốc 3N2Đ",
        "tripAttachment": {
            "hotelId": "h1",
            "hotelName": "Resort A",
            "destinationName": "Phú Quốc, Kiên Giang",
            "daysCount": 3,
            "items": [{"day": 1, "title": "Ngắm hoàng hôn", "location": "Bãi Dài"}],
        },
    }
}


def test_reel_itinerary_card_from_core():
    async def run():
        async with core_with({"/api/v1/posts/": httpx.Response(200, json=POST)}) as core:
            return await trip.post_itinerary(core, uuid4())

    answer = asyncio.run(run())
    assert answer.cards[0].kind == "itinerary"
    assert answer.cards[0].lines and answer.cards[0].lines[0].detail == "Ngắm hoàng hôn · Bãi Dài"


def test_hidden_reel_is_never_described():
    async def run():
        async with core_with({}) as core:
            return await trip.post_itinerary(core, uuid4())

    assert asyncio.run(run()).kind == "no_result"


def test_reel_hotel_room_check_keeps_price_off_the_facts():
    hotel = {
        "id": "h1",
        "name": "Resort A",
        "rooms": [
            {
                "isAvailable": True,
                "ratePlans": [{"totalPrice": 3_000_000, "pricePerNight": 1_500_000}],
            }
        ],
    }

    async def run():
        async with core_with(
            {
                "/api/v1/posts/": httpx.Response(200, json=POST),
                "/api/hotels/h1": httpx.Response(200, json=hotel),
            }
        ) as core:
            return await trip.check_room(core, uuid4(), date(2026, 11, 21), date(2026, 11, 23), 2)

    answer = asyncio.run(run())
    assert answer.kind == "answer"
    assert answer.cards[0].total_price == 3_000_000
    assert "3000000" not in json.dumps(answer.facts) and answer.facts[0]["available"] is True


# ---- Turn: a failing Skill degrades its part, never reads as "nothing found"


def test_failed_skill_is_reported_as_unchecked_not_empty():
    async def run():
        async with core_with({"/api/search": httpx.Response(503)}) as core:
            turn = ChatTurn(
                ChatRequest(conversation_id=uuid4(), message="da lat"),
                Understanding(intent="search", query="Đà Lạt"),
                core=core,
                weather=FakeWeather(),
                today=MONDAY,
            )
            return await turn.answer(), turn.degraded

    answer, degraded = asyncio.run(run())
    assert degraded == ["content"]
    assert answer.kind == "fallback" and "chưa kiểm được" in answer.text


def test_reel_questions_need_a_reel_in_view():
    async def run():
        async with core_with({}) as core:
            turn = ChatTurn(
                ChatRequest(conversation_id=uuid4(), message="lo trinh video nay"),
                Understanding(intent="post_itinerary", uses_context_post=True),
                core=core,
                weather=FakeWeather(),
                today=MONDAY,
            )
            return await turn.answer()

    assert "mở Tripi từ một reel" in asyncio.run(run()).text


def test_packing_uses_the_reel_destination_and_weather():
    async def run():
        async with core_with({"/api/v1/posts/": httpx.Response(200, json=POST)}) as core:
            turn = ChatTurn(
                ChatRequest(
                    conversation_id=uuid4(), message="can mang gi", context_post_id=uuid4()
                ),
                Understanding(intent="packing", day_ref="saturday", nights=1),
                core=core,
                weather=FakeWeather(),
                today=MONDAY,
            )
            return await turn.answer()

    answer = asyncio.run(run())
    assert answer.cards[0].kind == "checklist"
    lines = [line.label for line in answer.cards[0].lines or []]
    assert "Kem chống nắng" in lines and "Áo mưa mỏng hoặc ô" in lines


# ---- Responder: refs replaced by titles, bad sentences dropped, fixed text as fallback


class ScriptedLlm:
    def __init__(self, sentences, finish_reason="stop"):
        self.output = json.dumps({"sentences": sentences}, ensure_ascii=False)
        self.finish_reason = finish_reason

    async def agenerate(self, system, user, schema):
        return LlmResult(
            output=self.output,
            model_name="scripted",
            input_tokens=900,
            output_tokens=60,
            finish_reason=self.finish_reason,
        )


VIDEO_ANSWER = Answer(
    kind="answer",
    text="Tripi tìm được 1 video phù hợp.",
    cards=[
        Card.model_validate(
            {
                "ref": "r1",
                "id": "v1",
                "kind": "video",
                "title": "Săn mây Đà Lạt",
                "priceFrom": None,
                "priceBasis": "unavailable",
                "observedAt": "2026-11-16T00:00:00Z",
            }
        )
    ],
)


def test_responder_replaces_refs_and_drops_invented_prices(monkeypatch):
    llm = ScriptedLlm(["Xem [r1] nè ☁️", "Tour chỉ 299 nghìn thôi!", "Bấm thẻ để xem nha."])
    monkeypatch.setattr(responder, "get_role_llm", lambda role: llm)
    request = ChatRequest(conversation_id=uuid4(), message="san may da lat")
    sentences, result = asyncio.run(responder.respond(request, VIDEO_ANSWER))
    assert sentences == ["Xem Săn mây Đà Lạt nè ☁️", "Bấm thẻ để xem nha."]
    assert result.input_tokens == 900


def test_responder_cut_output_falls_back_to_fixed_text(monkeypatch):
    llm = ScriptedLlm(["Xem [r1] nè"], finish_reason="length")
    monkeypatch.setattr(responder, "get_role_llm", lambda role: llm)
    request = ChatRequest(conversation_id=uuid4(), message="san may da lat")
    sentences, _ = asyncio.run(responder.respond(request, VIDEO_ANSWER))
    assert sentences is None
    assert responder.split_for_stream(VIDEO_ANSWER.text) == ["Tripi tìm được 1 video phù hợp."]


def test_reel_without_a_summary_is_not_called_hidden():
    async def run():
        async with core_with({}) as core:  # core answers 404: no summary yet
            return await trip.post_reviews(core, uuid4())

    answer = asyncio.run(run())
    assert answer.kind == "no_result" and "chưa đủ bình luận" in answer.text
