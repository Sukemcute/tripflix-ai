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
from app.services.assistant.controller import (
    ControllerOutput,
    DayMonth,
    apply_guards,
    to_understanding,
)
from app.services.assistant.schemas import (
    Answer,
    Card,
    CardRef,
    ChatRequest,
    TripContext,
    Understanding,
)
from app.services.assistant.schemas import (
    Turn as HistoryTurn,
)
from app.services.assistant.skills import weather as weather_skill
from app.services.assistant.turn import Turn
from app.services.assistant.understand import build_understanding_input
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
    history: list[HistoryTurn] | None = None,
    today: date = TODAY,
) -> tuple[Answer, Turn]:
    request = ChatRequest(
        conversation_id=uuid4(),
        message=message,
        trip=trip,
        context_post_id=context_post_id,
        history=history or [],
    )
    parsed = to_understanding(out, trip, today)

    async def go():
        async with core.client() as client:
            turn = Turn(
                request, parsed, core=client, weather=weather or FakeWeather([]), today=today
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


def test_short_stay_date_reply_overrides_weekend_default():
    core = FakeCore(PLACE | {"/api/stays": stays(420_000)})
    answer, turn = run_turn(
        plan(intent="find_stay", place="Nha Trang"),
        core,
        message="Ngày 17 18",
        history=[
            HistoryTurn(
                role="assistant",
                kind="clarify",
                text="Bạn muốn nhận phòng và trả phòng vào ngày nào?",
            )
        ],
        trip=TripContext(place="Nha Trang", asked=True),
        today=date(2026, 11, 16),
    )
    params = dict(core.calls)["/api/stays"]
    assert (params["checkIn"], params["checkOut"]) == ("2026-11-17", "2026-11-18")
    assert answer.cards[0].check_in == date(2026, 11, 17)
    assert turn.next_trip(answer).date_to == date(2026, 11, 18)


def test_ambiguous_short_stay_dates_ask_before_searching():
    core = FakeCore(PLACE | {"/api/stays": stays(420_000)})
    answer, _ = run_turn(
        plan(intent="find_stay", place="Nha Trang", day_ref="this_weekend"),
        core,
        message="Ngày 30 1",
        history=[
            HistoryTurn(
                role="assistant",
                kind="clarify",
                text="Bạn muốn nhận phòng và trả phòng vào ngày nào?",
            )
        ],
        trip=TripContext(place="Nha Trang", asked=True),
        today=date(2026, 11, 16),
    )
    assert answer.kind == "clarify"
    assert not core.calls


def test_cancel_current_destination_clears_trip_instead_of_refusing():
    core = FakeCore({})
    old_reel = uuid4()
    answer, turn = run_turn(
        plan(intent="refusal"),
        core,
        message="Tôi không muốn đi đà lạt nữa",
        trip=TripContext(
            place="Đà Lạt",
            date_from=IN_5,
            date_to=IN_6,
            reel_id=old_reel,
            asked=True,
        ),
        context_post_id=old_reel,
    )
    assert answer.kind == "clarify"
    assert "đổi sang" in answer.text
    assert turn.next_trip(answer) == TripContext()
    assert not core.calls


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


# ---- guards after the Controller: what the message does not say is not believed
# (live eval 2026-11-16 of Controller v3)


@pytest.mark.parametrize(
    ("message", "said", "has_reel", "want"),
    [
        ("thoi tiet hom do sao", {"intent": "weather", "day_ref": "today"}, False,
         {"day_ref": "none"}),
        ("bay HAN DAD 21/11 1 em be", {"intent": "find_flight", "children": 1, "round_trip": True},
         False, {"infants": 1, "children": None, "round_trip": False}),
        ("ks vung tau dem 21/11 con phong k",
         {"intent": "check_room", "hotel_name": "Vinpearl hoặc khách sạn trong khu vực"}, False,
         {"intent": "find_stay", "hotel_name": ""}),
        ("ks trong reel t7 nay con phong k", {"intent": "check_room"}, True,
         {"intent": "check_room"}),
        ("nguoi di roi noi gi ve cho nay", {"intent": "ack"}, True, {"intent": "search"}),
        ("homestay da lat cuoi tuan sau", {"intent": "search", "place": "Đà Lạt"}, False,
         {"intent": "find_stay"}),
        ("mai da lat co mua k", {"intent": "packing", "day_ref": "tomorrow"}, False,
         {"intent": "weather", "day_ref": "tomorrow"}),
        ("mai da lat mang ao gi", {"intent": "packing"}, False, {"intent": "packing"}),
        ("ngay 2 di dau", {"intent": "post_itinerary", "start": {"day": 2, "month": 11}}, True,
         {"itinerary_day": 2, "start": None}),
        ("vay du roi", {"intent": "ack"}, False, {"intent": "ack"}),
        # live eval of Controller v5 (16/11)
        ("muon di vung tau 2n1d", {"intent": "plan_trip", "place": "Vũng Tàu"}, False,
         {"intent": "search"}),
        ("đặt phòng giúp mình", {"intent": "plan_trip"}, False, {"intent": "find_stay"}),
        ("mình muốn đi chơi 3 ngày", {"intent": "plan_trip"}, False,
         {"intent": "clarify", "missing": "place"}),
        ("xếp chuyến vũng tàu 2n1đ cho mình", {"intent": "plan_trip", "place": "Vũng Tàu"},
         False, {"intent": "plan_trip"}),
        # Bảo on staging 17/11: these went to search and showed reels
        ("Tôi muốn đi chơi Đà Nẵng, lên cho tôi lịch trình",
         {"intent": "plan_trip", "place": "Đà Nẵng"}, False, {"intent": "plan_trip"}),
        ("gợi ý lộ trình đà nẵng 3 ngày giúp mình", {"intent": "plan_trip", "place": "Đà Nẵng"},
         False, {"intent": "plan_trip"}),
        ("mình ở sài gòn", {"intent": "change_transport", "to_city": "Vũng Tàu"}, False,
         {"from_city": "TP.HCM"}),
        ("đi đà nẵng từ hà nội bằng gì", {"intent": "change_transport", "to_city": "Đà Nẵng"},
         False, {"from_city": "Hà Nội"}),
        ("lộ trình video này", {"intent": "find_reel"}, True, {"intent": "post_itinerary"}),
        ("lộ trình video này", {"intent": "find_reel"}, False, {"intent": "post_itinerary"}),
        # chain reel-6.1 with Controller v5 (17/11)
        ("Quay lại lộ trình reel đó, ngày cuối đi đâu?",
         {"intent": "post_itinerary", "reel_query": "đà lạt"}, True, {"reel_query": ""}),
        ("Ngày thứ hai của video này có điểm gì?",
         {"intent": "post_itinerary", "reel_query": "video này"}, True, {"reel_query": ""}),
        ("Cho mình xem lịch trình của reel săn mây Đà Lạt vừa gợi ý",
         {"intent": "post_itinerary", "reel_query": "săn mây Đà Lạt"}, False,
         {"reel_query": "săn mây Đà Lạt"}),
        ("ks trong video này còn phòng cuối tuần không",
         {"intent": "check_room", "hotel_name": "ks trong video này còn phòng cuối tuần không"},
         True, {"hotel_name": ""}),
        ("làm giúp bài văn tả cảnh biển", {"intent": "search"}, False, {"intent": "refusal"}),
        ("mình ở sài gòn", {"intent": "plan_trip", "place": "Vũng Tàu"}, False,
         {"intent": "change_transport", "from_city": "TP.HCM"}),
        # live eval of Controller v5, second run (17/11)
        ("mình ở sài gòn",
         {"intent": "change_transport", "to_city": "Vũng Tàu", "missing": "origin"},
         False, {"from_city": "TP.HCM", "missing": "none"}),
        ("tối 21/11 ở vũng tàu chỗ nào ok", {"intent": "find_stay", "place": "Vũng Tàu"}, False,
         {"intent": "find_stay", "from_city": ""}),
        ("ăn gì ở Huế cho đúng vị", {"intent": "search", "place": "Huế"}, False,
         {"intent": "search", "from_city": ""}),
        ("đi đà nẵng từ hà nội bằng gì", {"intent": "find_flight", "to_city": "Đà Nẵng"}, False,
         {"from_city": "Hà Nội"}),
        ("mình ở sài gòn",
         {"intent": "change_transport", "from_airport": "SGN", "missing": "origin"},
         False, {"from_city": "TP.HCM", "missing": "none"}),
        ("lên lịch trình đà Lạt 3 ngày đi nhiều chỗ", {"intent": "plan_trip", "place": "Đà Lạt"},
         False, {"pace": "packed"}),
        ("xếp lịch vũng tàu thong thả thôi", {"intent": "plan_trip", "place": "Vũng Tàu"},
         False, {"pace": "relaxed"}),
        ("Thời tiết Đà Lạt thứ Bảy thế nào?", {"intent": "post_itinerary"}, True,
         {"intent": "weather"}),
        # live eval of Controller v4 (16/11)
        ("ks da nang t7 nay 2 nguoi", {"intent": "find_flight", "day_ref": "saturday"}, False,
         {"intent": "find_stay"}),
        ("bay da nang thu bay nay", {"intent": "find_flight"}, False, {"intent": "find_flight"}),
        ("chuyen bay ha noi da nang 21/11 sau 3h chieu",
         {"intent": "find_flight", "depart_before": "15:00"}, False,
         {"depart_after": "15:00", "depart_before": None}),
        ("bay sg ra hn truoc 9h sang", {"intent": "find_flight"}, False,
         {"depart_before": "09:00"}),
        ("reel nay di may ngay", {"intent": "post_itinerary"}, True, {"asks_days_count": True}),
        ("mình chốt vậy", {"intent": "packing"}, False, {"intent": "ack"}),
        ("Đi Đà Lạt mang gì, có áo khoác rồi", {"intent": "packing"}, False,
         {"packing_have": ["ao khoac"]}),
        ("chi can 2 mon thoi", {"intent": "packing", "packing_only": ["2 món"]}, False,
         {"packing_limit": 2, "packing_only": []}),
        ("Hii 😄", {"intent": "packing"}, True, {"intent": "greeting"}),
        ("Hiiii!!!", {"intent": "packing"}, False, {"intent": "greeting"}),
        ("Hi, tìm khách sạn Đà Lạt", {"intent": "search", "place": "Đà Lạt"}, False,
         {"intent": "find_stay"}),
        ("ban lam duoc gi", {"intent": "refusal"}, False, {"intent": "identity"}),
        ("bay re nhat tu ha noi vao sai gon t7",
         {"intent": "refusal", "from_airport": "HAN", "to_airport": "SGN"}, False,
         {"intent": "find_flight"}),
        ("giai giup bai toan dao ham", {"intent": "refusal"}, False, {"intent": "refusal"}),
    ],
)  # fmt: skip
def test_guards_drop_what_the_message_does_not_say(message, said, has_reel, want):
    got = apply_guards(plan(**said), message, has_reel=has_reel).model_dump()
    assert {key: got[key] for key in want} == want


@pytest.mark.parametrize("intent", ["weather", "packing"])
def test_weather_and_packing_prefer_tomorrow_to_a_remembered_or_invented_day(intent):
    message = "Đi Đà Lạt ngày mai có cần mang áo khoác vì trời mưa lạnh không?"
    remembered = TripContext(place="Đà Lạt", date_from=TODAY + timedelta(days=4))
    mistaken = plan(intent=intent, day_ref="none", start={"day": 18, "month": 11})
    guarded = apply_guards(mistaken, message, has_reel=False)
    window = planner.day_window(to_understanding(guarded, remembered, TODAY), TODAY)
    assert window.start == window.end == TODAY + timedelta(days=1)


def test_verifier_accepts_an_itinerary_with_a_numeric_day_count():
    sentence = "Lộ trình này đi 3 ngày."
    facts = [{"ref": "r1", "kind": "itinerary", "days": 3}]
    kept, dropped = verify([sentence], facts, {"r1"}, "Reel này đi mấy ngày?", today=TODAY)
    assert kept == [sentence]
    assert not dropped


@pytest.mark.parametrize("query", ["reel này", "lộ trình video này", "video đó"])
def test_words_pointing_at_the_open_reel_are_not_a_name(query):
    from app.services.assistant.skills.trip import matches, names_a_reel

    assert not names_a_reel(query)  # points at the open reel: never "another reel"
    assert names_a_reel(f"{query} săn mây") and matches(f"{query} săn mây", "Săn mây 4h sáng")
    post = {
        "post": {
            "id": "p",
            "authorId": "a",
            "title": "Nha Trang 3N2Đ",
            "tripAttachment": {"daysCount": 3, "items": [{"day": 1, "title": "Cáp treo"}]},
        }
    }
    answer, _ = run_turn(
        plan(intent="post_itinerary", reel_query=query, asks_days_count=True),
        FakeCore({"/api/v1/posts/": post}),
        context_post_id=uuid4(),
    )
    assert answer.cards and answer.lead == "Reel này đi 3 ngày."


def test_reel_picked_by_name_from_cards_is_not_rejected_by_its_post_title():
    """Chain §6.1 turn 3: the model repeats "săn mây Đà Lạt"; the post's title differs."""
    reel = uuid4()
    post = {
        "post": {
            "id": str(reel),
            "authorId": "a",
            "title": "Đà Lạt 3N2Đ",
            "tripAttachment": {
                "destinationName": "Đà Lạt",
                "daysCount": 3,
                "items": [{"day": 2, "title": "Cầu Đất", "location": "Trại Mát"}],
            },
        }
    }
    trip = TripContext(
        reel_id=reel,
        last_cards=[CardRef(ref="r1", kind="video", id=str(reel), title="Săn mây 4h sáng")],
    )
    answer, _ = run_turn(
        plan(intent="post_itinerary", reel_query="săn mây Đà Lạt", itinerary_day=2),
        FakeCore({"/api/v1/posts/": post}),
        trip=trip,
    )
    assert answer.cards[0].kind == "itinerary" and "Cầu Đất" in (answer.lead or "")


# ---- airports from city names (plan A2, T8): Core knows the code, the LLM does not guess it


def airports(*codes: str) -> dict:
    return {"items": [{"type": "airport", "refId": c, "name": f"Sân bay {c}"} for c in codes]}


class AirportCore(FakeCore):
    """Answers /api/suggest by the city asked; everything else by path like FakeCore."""

    def __init__(self, by_city: dict[str, dict], routes: Mapping[str, object]):
        super().__init__(routes)
        self.by_city = by_city

    def client(self) -> httpx.AsyncClient:
        def handle(request: httpx.Request) -> httpx.Response:
            self.calls.append((request.url.path, dict(request.url.params)))
            if request.url.path == "/api/suggest":
                body = self.by_city.get(request.url.params["q"], {"items": []})
                return httpx.Response(200, json=body)
            for prefix, body in self.routes.items():
                if request.url.path.startswith(prefix):
                    return httpx.Response(200, json=body)
            return httpx.Response(404)

        return httpx.AsyncClient(
            base_url="https://core.test", transport=httpx.MockTransport(handle)
        )


def test_city_names_become_airport_codes_through_core():
    core = AirportCore(
        {"TP.HCM": airports("SGN"), "Hà Nội": airports("HAN")},
        {"/api/flights": {"flights": [flight("VN1", "09:00", 900_000)]}},
    )
    answer, _ = run_turn(
        plan(intent="find_flight", from_city="TP.HCM", to_city="Hà Nội", start=dm(IN_5)), core
    )
    params = dict(core.calls)["/api/flights"]
    assert (params["from"], params["to"]) == ("SGN", "HAN")
    card = answer.cards[0]
    # Everything the app needs to open its own flight screen for the same search.
    assert (card.kind, card.from_airport, card.to_airport, card.passengers) == (
        "flight",
        "SGN",
        "HAN",
        2,
    )


def test_a_city_without_an_airport_is_said_not_searched():
    core = AirportCore({"TP.HCM": airports("SGN")}, {})
    answer, _ = run_turn(
        plan(intent="find_flight", from_city="TP.HCM", to_city="Vũng Tàu", start=dm(IN_5)), core
    )
    assert answer.kind == "no_result" and "Vũng Tàu" in answer.text
    assert "/api/flights" not in core.paths()


def test_two_airports_for_one_name_are_asked_about():
    core = AirportCore({"Miền Bắc": airports("HAN", "HPH")}, {})
    answer, _ = run_turn(
        plan(intent="find_flight", from_city="Miền Bắc", to_airport="DAD", start=dm(IN_5)), core
    )
    assert answer.kind == "clarify" and "HAN" in answer.text and "HPH" in answer.text


def test_only_the_destination_city_asks_for_the_origin():
    answer, _ = run_turn(plan(intent="clarify", missing="origin", to_city="Đà Lạt"), FakeCore({}))
    assert answer.text == "Bạn bay từ thành phố nào đi?"


@pytest.mark.parametrize(
    ("message", "ordinal"),
    [("lấy cái thứ 1", 1), ("chọn chỗ thứ hai nha", 2), ("lay cai dau tien", 1)],
)
def test_picking_an_option_on_screen_is_a_selection(message, ordinal):
    said = plan(intent="change_stay")
    got = apply_guards(said, message, has_reel=False, has_options=True)
    assert (got.intent, got.card_ordinal) == ("select_option", ordinal)
    assert apply_guards(said, message, has_reel=False).intent == "change_stay"  # nothing shown


def test_the_latest_message_comes_after_the_history():
    # chain vung-tau-0A2 (17/11): with the message before the history, v5 answered the
    # user's previous message ("đổi chỗ ở…" read as "mình ở sài gòn").
    request = ChatRequest(
        conversation_id=uuid4(),
        message="đổi chỗ ở khác gần biển hơn",
        history=[
            HistoryTurn(role="user", text="mình ở sài gòn"),
            HistoryTurn(role="assistant", text="Từ TP.HCM đi Vũng Tàu bạn có thể đi xe khách nè."),
        ],
    )
    keys = list(json.loads(build_understanding_input(request)))
    assert keys[-1] == "message" and keys.index("history") < keys.index("message")
