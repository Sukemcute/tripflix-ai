"""One test per defect of the Expo Web report (docs/evidence/TF31-bao-cao-loi-tripi-expo-web.md).

The Controller is replaced by its output; the rest (date rules, Turn, Skills, Verifier,
Responder) is the real code, and a fake Core records every request it gets.
"""

import asyncio
import json
from collections.abc import Mapping
from datetime import date, timedelta
from uuid import uuid4

import httpx
import pytest

from app.clients.llm.base import LlmResult
from app.clients.weather import DayWeather, Place, describe_sky
from app.services.assistant import planner, responder
from app.services.assistant.controller import ControllerOutput, DayMonth, to_understanding
from app.services.assistant.schemas import (
    Answer,
    Card,
    CardRef,
    ChatRequest,
    TripContext,
    Understanding,
)
from app.services.assistant.skills import weather as weather_skill
from app.services.assistant.turn import Turn
from app.services.assistant.verifier import verify
from evals.assistant.run import controller_plan

# Skills check "not in the past" against the real clock, so every date is relative to it.
TODAY = planner.today_in_vietnam()
IN_5 = TODAY + timedelta(days=5)
IN_6 = TODAY + timedelta(days=6)


def dm(day: date) -> DayMonth:
    return DayMonth(day=day.day, month=day.month)


plan = controller_plan


class FakeCore:
    """Answers by path prefix and keeps (path, params) of each call."""

    def __init__(self, routes: Mapping[str, object]):
        self.routes, self.calls = routes, []

    def client(self) -> httpx.AsyncClient:
        def handle(request: httpx.Request) -> httpx.Response:
            self.calls.append((request.url.path, dict(request.url.params)))
            for prefix, body in self.routes.items():
                if request.url.path.startswith(prefix):
                    return (
                        body if isinstance(body, httpx.Response) else httpx.Response(200, json=body)
                    )
            return httpx.Response(404)

        return httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(handle)
        )

    def paths(self) -> list[str]:
        return [path for path, _ in self.calls]


class FakeWeather:
    def __init__(self, days: list[DayWeather]):
        self.days = days

    async def find_place(self, name):
        return Place(name, 10.3, 107.0)

    async def forecast(self, place, start, end):
        return [d for d in self.days if start <= d.day <= end]


def run_turn(
    out: ControllerOutput,
    core: FakeCore,
    *,
    message: str = "...",
    trip: TripContext | None = None,
    context_post_id=None,
    weather: FakeWeather | None = None,
) -> tuple[Answer, Turn]:
    request = ChatRequest(
        conversation_id=uuid4(), message=message, trip=trip, context_post_id=context_post_id
    )
    parsed = to_understanding(out, trip, TODAY)

    async def go():
        async with core.client() as client:
            turn = Turn(
                request, parsed, core=client, weather=weather or FakeWeather([]), today=TODAY
            )
            return await turn.answer(), turn

    return asyncio.run(go())


PLACE = {"/api/suggest": {"items": [{"type": "place", "refId": "vt"}]}}


def stays(*prices: int) -> dict:
    return {
        "items": [
            {"hotelId": f"h{p}", "name": f"Nhà nghỉ {p}", "unitPrice": p, "totalPrice": p}
            for p in prices
        ]
    }


# ---- dates: the LLM never writes a year, code never searches another range


def test_v11_b09_year_comes_from_code_not_the_model():
    core = FakeCore(PLACE | {"/api/stays": stays(400_000)})
    answer, _ = run_turn(
        plan(intent="find_stay", place="Vũng Tàu", start=dm(IN_5), end=dm(IN_6)), core
    )
    params = dict(core.calls)["/api/stays"]
    assert (params["checkIn"], params["checkOut"]) == (IN_5.isoformat(), IN_6.isoformat())
    assert answer.kind == "answer"


@pytest.mark.parametrize(
    ("start", "end", "words"),
    [(IN_6, IN_5, "trước ngày nhận"), (IN_5, IN_5, "qua đêm")],  # B11, B12
)
def test_b11_b12_a_range_that_makes_no_sense_is_asked_not_replaced(start, end, words):
    core = FakeCore(PLACE | {"/api/stays": stays(400_000)})
    answer, _ = run_turn(
        plan(intent="find_stay", place="Vũng Tàu", start=dm(start), end=dm(end)), core
    )
    assert answer.kind == "clarify" and words in answer.text
    assert "/api/stays" not in core.paths()


def test_b16_a_start_day_alone_is_one_night_and_said_so():
    core = FakeCore(PLACE | {"/api/stays": stays(400_000)})
    answer, _ = run_turn(plan(intent="find_stay", place="Vũng Tàu", start=dm(IN_5)), core)
    assert dict(core.calls)["/api/stays"]["checkOut"] == IN_6.isoformat()
    assert answer.lead and "1 đêm" in answer.lead and f"{IN_5:%d/%m}" in answer.lead


# ---- constraints the user said are kept


def test_d01_d03_price_cap_is_sent_and_checked_again():
    core = FakeCore(PLACE | {"/api/stays": stays(340_000, 380_000)})  # core ignored the cap
    answer, _ = run_turn(
        plan(
            intent="find_stay",
            place="Vũng Tàu",
            start=dm(IN_5),
            nights=1,
            price_max_per_night=250_000,
        ),
        core,
    )
    assert dict(core.calls)["/api/stays"]["priceMax"] == "250000"
    assert answer.kind == "no_result" and answer.cards == [] and "250.000đ" in answer.text


def flight(key: str, depart: str, price: int) -> dict:
    return {
        "productId": f"{key}-{price}",
        "name": f"VN {key}",
        "flightKey": key,
        "departTime": depart,
        "isAvailable": True,
        "priceFrom": price,
        "fares": [],
    }


def test_i08_i09_time_filter_runs_before_the_top_five_and_cabins_merge():
    early = [flight(f"E{i}", f"0{i}:30", 900_000) for i in range(1, 7)]
    late = [flight("L1", "17:30", 1_200_000), flight("L1", "17:30", 2_500_000)]
    core = FakeCore({"/api/flights": {"flights": early + late}})
    answer, _ = run_turn(
        plan(
            intent="find_flight",
            from_airport="HAN",
            to_airport="DAD",
            start=dm(IN_5),
            depart_after="15:00",
        ),
        core,
    )
    assert [c.title for c in answer.cards] == ["VN L1 · 17:30"]
    assert answer.cards[0].price_from == 1_200_000


# ---- the hotel the user names wins over the reel in view


def test_r11_named_hotel_beats_the_reel_hotel():
    hotel = {"id": "vlnt", "name": "Vinpearl Luxury Nha Trang", "rooms": []}
    core = FakeCore(
        {
            "/api/suggest": {
                "items": [{"type": "hotel", "refId": "vlnt", "name": "Vinpearl Luxury Nha Trang"}]
            },
            "/api/hotels/vlnt": hotel,
        }
    )
    answer, _ = run_turn(
        plan(
            intent="check_room",
            hotel_name="Vinpearl Luxury Nha Trang",
            day_ref="tomorrow",
        ),
        core,
        context_post_id=uuid4(),  # a Da Lat reel is open
    )
    assert "/api/v1/posts/" not in "".join(core.paths())
    assert answer.cards[0].title == "Vinpearl Luxury Nha Trang"
    assert "Vinpearl Luxury Nha Trang" in (answer.lead or "")


# ---- social turns call no Skill


@pytest.mark.parametrize("intent", ["greeting", "thanks", "ack", "goodbye", "identity"])
def test_a04_a16_v12_social_turns_call_nothing(intent):
    core = FakeCore({})
    trip = TripContext(place="Đà Lạt")
    answer, _ = run_turn(plan(intent=intent), core, trip=trip)
    assert core.calls == [] and answer.cards == []
    assert answer.kind == "answer"  # "bye" is not a refusal (V12)


# ---- weather: the asked day, no past, numbers tied to their day

FORECAST = [
    DayWeather(TODAY + timedelta(days=1), 18, 24, 80, describe_sky(61)),
    DayWeather(TODAY + timedelta(days=2), 17, 23, 47, describe_sky(3)),
    DayWeather(IN_5, 12, 20, 80, describe_sky(80)),
]


def test_w01_weather_keeps_the_asked_day():
    answer, _ = run_turn(
        plan(intent="weather", place="Đà Lạt", start=dm(IN_5)),
        FakeCore({}),
        weather=FakeWeather(FORECAST),
    )
    assert [d["day"] for d in answer.facts[0]["days"]] == [weather_skill.day_label(IN_5)]


def test_c04_yesterday_has_no_weather():
    answer, _ = run_turn(
        plan(intent="weather", place="Đà Lạt", day_ref="yesterday"),
        FakeCore({}),
        weather=FakeWeather(FORECAST),
    )
    assert answer.kind == "no_result" and "đã qua" in answer.text


def weather_facts() -> list[dict]:
    return [
        {
            "ref": "r1",
            "kind": "weather",
            "place": "Đà Lạt",
            "days": [
                {
                    "day": weather_skill.day_label(d.day),
                    "minC": d.min_c,
                    "maxC": d.max_c,
                    "rainChance": d.rain_chance,
                }
                for d in FORECAST
            ],
        }
    ]


def test_w14_t20_a_number_from_another_day_is_dropped():
    tomorrow_rain = "Mai Đà Lạt mưa 47% nha."  # 47% is the day after tomorrow
    kept, dropped = verify([tomorrow_rain], weather_facts(), {"r1"}, "mai mua k", today=TODAY)
    assert kept == [] and dropped["V8_wrong_day"] == 1
    right = "Mai Đà Lạt mưa 80% nha."
    assert verify([right], weather_facts(), {"r1"}, "mai mua k", today=TODAY)[0] == [right]


def test_c04_past_weather_sentences_are_dropped():
    kept, _ = verify(["Hôm qua Đà Lạt mưa 80%."], weather_facts(), {"r1"}, "hom qua", today=TODAY)
    assert kept == []


# ---- packing: what the user has, does not do, or wants only


def packing_items(**fields) -> list[str]:
    understood = Understanding.model_validate({"intent": "packing"} | fields)
    days = [DayWeather(IN_5, 12, 20, 80, describe_sky(80))]
    return [item for item, _ in weather_skill.packing_list(understood, "Vũng Tàu", days, 1)]


def test_k06_items_the_user_has_are_not_suggested():
    assert "Áo khoác" in packing_items()
    assert "Áo khoác" not in packing_items(packing_have=["áo khoác"])


def test_k08_no_beach_means_no_beach_items():
    assert "Kem chống nắng" in packing_items()  # Vũng Tàu is a beach by default
    assert "Kem chống nắng" not in packing_items(is_beach_trip=False)


def test_k09_only_two_items():
    assert len(packing_items(packing_limit=2)) == 2


# ---- Responder: no "thẻ thẻ", the answer survives when only the CTA does


class ScriptedLlm:
    def __init__(self, sentences):
        self.output = json.dumps({"sentences": sentences}, ensure_ascii=False)

    async def agenerate(self, system, user, schema):
        return LlmResult(
            output=self.output,
            model_name="scripted",
            input_tokens=10,
            output_tokens=10,
            finish_reason="stop",
        )


CHECKLIST = Answer(
    kind="answer",
    text="Tripi gợi ý mấy món nên mang theo ở thẻ bên dưới nha.",
    cards=[
        Card.model_validate(
            {
                "ref": "r1",
                "id": "packing",
                "kind": "checklist",
                "title": "Nên mang theo",
                "priceFrom": None,
                "priceBasis": "unavailable",
                "observedAt": "2026-11-16T00:00:00Z",
            }
        )
    ],
    facts=[{"ref": "r1", "kind": "checklist", "items": [{"item": "Áo khoác", "why": "lạnh"}]}],
)


def respond_with(monkeypatch, sentences, answer=CHECKLIST) -> list[str] | None:
    monkeypatch.setattr(responder, "get_role_llm", lambda role: ScriptedLlm(sentences))
    request = ChatRequest(conversation_id=uuid4(), message="can mang gi")
    return asyncio.run(responder.respond(request, answer, today=TODAY))[0]


def test_t24_card_ref_never_doubles_the_word_card(monkeypatch):
    sentences = respond_with(monkeypatch, ["Mang Áo khoác nha.", "Bấm thẻ [r1] để xem nha."])
    assert sentences and all("thẻ thẻ" not in s for s in sentences)


def test_t25_only_a_call_to_action_left_brings_back_the_fixed_text(monkeypatch):
    sentences = respond_with(monkeypatch, ["Mang 5 cái Áo Lông Vũ nha.", "Bấm [r1] xem nha."])
    assert sentences and sentences[0] == CHECKLIST.text


def test_reel_named_from_last_cards_is_the_one_opened():
    post = {"post": {"id": "p2", "authorId": "a", "title": "Săn mây", "tripAttachment": None}}
    core = FakeCore({"/api/v1/posts/": post})
    second = uuid4()
    trip = TripContext(
        last_cards=[
            CardRef(ref="r1", kind="video", id=str(uuid4()), title="Biển Vũng Tàu"),
            CardRef(ref="r2", kind="video", id=str(second), title="Săn mây Đà Lạt 4h sáng"),
        ]
    )
    _, turn = run_turn(plan(intent="post_itinerary", reel_query="san may"), core, trip=trip)
    assert turn.reel_id == second
    assert core.paths() == [f"/api/v1/posts/{second}"]
