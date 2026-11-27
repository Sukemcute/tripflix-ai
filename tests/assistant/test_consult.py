"""Destination catalog and trip preferences (consult intent, TF31)."""

import asyncio
import json
import logging
import re
from datetime import date
from typing import Any, Literal
from uuid import uuid4

import httpx
import pytest

from app.clients.llm.base import LlmResult
from app.services.assistant import consultant
from app.services.assistant.consultant import (
    ConsultOutput,
    consult,
    fallback_consult_answer,
)
from app.services.assistant.controller import DayMonth, apply_guards
from app.services.assistant.destinations import destinations_by_id, merge_prefs
from app.services.assistant.schemas import (
    Answer,
    Awaiting,
    ChatRequest,
    TravelPrefs,
    TripContext,
    Understanding,
)
from app.services.assistant.turn import Turn
from app.services.assistant.understand import build_understanding_input
from app.services.summary.schemas import strict_json_schema
from evals.assistant.run import FakeWeather, controller_plan, fake_core


def test_catalog_loads_and_is_valid() -> None:
    catalog = destinations_by_id()
    assert len(catalog) >= 40
    for destination_id, destination in catalog.items():
        assert re.fullmatch(r"[a-z0-9-]+", destination_id)
        assert destination.id == destination_id
        assert destination.name.strip()
        assert all(1 <= month <= 12 for month in destination.good_months)
        assert 2 <= len(destination.highlights) <= 4
        assert not any(re.search(r"\d", text) for text in destination.highlights)
    assert {d.region for d in catalog.values()} == {"bac", "trung", "nam", "tay-nguyen"}


def test_catalog_has_core_places() -> None:
    names = {key: place.name for key, place in destinations_by_id().items()}
    expected = {
        "da-lat": "Đà Lạt",
        "vung-tau": "Vũng Tàu",
        "nha-trang": "Nha Trang",
        "da-nang": "Đà Nẵng",
        "phu-quoc": "Phú Quốc",
        "quy-nhon": "Quy Nhơn",
        "sa-pa": "Sa Pa",
        "ha-giang": "Hà Giang",
        "hoi-an": "Hội An",
        "ninh-binh": "Ninh Bình",
    }
    assert {key: names.get(key) for key in expected} == expected


def test_merge_prefs_new_wins_empty_keeps_old() -> None:
    old = TravelPrefs(vibe=["quiet"], terrain=["beach"], nights=2)
    new = TravelPrefs(terrain=["mountain"], mood="đang buồn")
    merged = merge_prefs(old, new)
    assert merged.vibe == ["quiet"]
    assert merged.terrain == ["mountain"]
    assert merged.nights == 2
    assert merged.mood == "đang buồn"
    assert merge_prefs(None, new) == new


def test_trip_context_round_trips_prefs() -> None:
    context = TripContext(prefs=TravelPrefs(vibe=["quiet"], budget_per_person=2_000_000))
    dumped = context.model_dump(mode="json", by_alias=True)
    assert dumped["prefs"]["vibe"] == ["quiet"]
    assert dumped["prefs"]["budgetPerPerson"] == 2_000_000
    assert TripContext.model_validate(dumped) == context


def guarded(message: str, *, awaiting: Awaiting | None = None, **said: object) -> str:
    return apply_guards(controller_plan(**said), message, has_reel=False, awaiting=awaiting).intent


@pytest.mark.parametrize("intent", ["off_topic", "ack"])
def test_long_social_message_without_place_becomes_consult(intent: str) -> None:
    message = "tôi vừa thất nghiệp buồn quá muốn tìm chỗ đi chơi cuối tuần"
    assert guarded(message, intent=intent) == "consult"


def test_idea_clarify_without_place_becomes_consult() -> None:
    assert guarded("vậy đi biển đâu cho chill", intent="clarify", place="") == "consult"


def test_idea_with_place_stays_search() -> None:
    assert guarded("đà lạt cuối tuần chơi gì", intent="clarify", place="Đà Lạt") != "consult"
    assert guarded("đà lạt cuối tuần chơi gì", intent="off_topic", place="Đà Lạt") == "search"
    long_ack = "ok cảm ơn bạn nhiều nha mình sẽ đi Đà Lạt chơi"
    assert guarded(long_ack, intent="ack", place="Đà Lạt") == "search"


def test_reel_request_stays_find_reel() -> None:
    assert guarded("tìm reel cuối tuần đi đâu", intent="find_reel") == "find_reel"


def guard(message: str, *, has_reel: bool = False, **said):
    return apply_guards(controller_plan(**said), message, has_reel=has_reel)


def test_consult_with_reel_word_becomes_find_reel() -> None:
    got = guard(
        "tìm reel cuối tuần đi đâu",
        intent="consult",
        query="gợi ý nơi đi cuối tuần",
        reel_query="cuối tuần đi đâu",
    )
    assert (got.intent, got.reel_query) == ("find_reel", "cuối tuần đi đâu")


def test_consult_naming_a_place_becomes_search() -> None:
    got = guard("da lat cuoi tuan choi gi", intent="consult", query="da lat cuoi tuan choi gi")
    assert (got.intent, got.place, got.query) == ("search", "Đà Lạt", "da lat cuoi tuan choi gi")
    assert guard("đi vũng tàu chơi gì", intent="consult").place == "Vũng Tàu"
    # an origin city is where they start, not where they want to go
    assert guard("từ sài gòn đi đâu chơi", intent="consult").intent == "consult"


def test_tim_phong_with_place_is_find_stay() -> None:
    message = "Tìm phòng Quy Nhơn"
    assert guarded(message, intent="search", place="Quy Nhơn") == "find_stay"
    awaiting = Awaiting(intent="consult", missing="place")
    got = guarded(message, awaiting=awaiting, intent="search", place="Quy Nhơn")
    assert got == "find_stay"


def test_consult_with_place_and_stay_cue_is_find_stay() -> None:
    got = guard("muốn đi đâu đó chill, tìm phòng đà lạt giúp mình", intent="consult")
    assert (got.intent, got.place) == ("find_stay", "Đà Lạt")


def test_consult_with_place_and_weather_cue_is_weather() -> None:
    got = guard("đà lạt cuối tuần có mưa không", intent="consult")
    assert (got.intent, got.place) == ("weather", "Đà Lạt")


def test_reel_open_day_two_is_post_itinerary() -> None:
    got = guard(
        "ngay thu hai di dau",
        has_reel=True,
        intent="consult",
        day_ref="monday",
        uses_context_post=True,
    )
    assert (got.intent, got.itinerary_day, got.day_ref) == ("post_itinerary", 2, "none")


def test_reel_open_weekend_ideas_stay_consult() -> None:
    for uses_context_post in (False, True):  # the model sets the flag on any ask in a reel
        got = guard(
            "cuối tuần này đi đâu",
            has_reel=True,
            intent="consult",
            uses_context_post=uses_context_post,
        )
        assert got.intent == "consult"


def test_consult_without_place_stays_consult() -> None:
    got = guard("cuối tuần đi đâu chơi", intent="consult", query="gợi ý nơi đi chơi cuối tuần")
    assert (got.intent, got.place) == ("consult", "")


def test_mood_without_travel_wish_stays_off_topic() -> None:
    assert guarded("chán quá à", intent="off_topic") == "off_topic"


def test_awaiting_consult_short_reply_is_consult() -> None:
    awaiting = Awaiting(intent="consult", missing="place")
    assert guarded("chill thôi", awaiting=awaiting, intent="search") == "consult"
    # naming a place leaves the consult
    assert guarded("đà lạt đi", awaiting=awaiting, intent="search", place="Đà Lạt") == "search"


def test_controller_input_has_prefs() -> None:
    def trip_of(trip: TripContext) -> dict:
        request = ChatRequest(conversation_id=uuid4(), message="chill thôi", trip=trip)
        return json.loads(build_understanding_input(request))["trip"]

    assert "prefs" not in trip_of(TripContext())
    prefs = TravelPrefs(vibe=["quiet"], budget_per_person=2_000_000)
    assert trip_of(TripContext(prefs=prefs))["prefs"]["budgetPerPerson"] == 2_000_000


# ---- Consultant: the LLM chooses, code keeps to the catalog

TODAY = date(2026, 11, 26)


class ScriptedConsultLlm:
    def __init__(self, finish_reason: str = "stop", **fields: Any) -> None:
        output = {
            "sentences": ["Bạn thích biển hay núi nè?"],
            "prefs": {},
            "destination_ids": [],
            "chips": [],
            "is_done_asking": False,
        } | fields
        self.output = json.dumps(output, ensure_ascii=False)
        self.finish_reason = finish_reason
        self.user = ""

    async def agenerate(self, system: str, user: str, schema: dict) -> LlmResult:
        self.user = user
        return LlmResult(
            output=self.output,
            model_name="scripted",
            input_tokens=5000,
            output_tokens=80,
            finish_reason=self.finish_reason,
        )


def run_consult(monkeypatch, message: str = "đi đâu chill chill", **fields: Any):
    llm = ScriptedConsultLlm(**fields)
    monkeypatch.setattr(consultant, "get_role_llm", lambda role: llm)
    request = ChatRequest(conversation_id=uuid4(), message=message)
    answer, prefs = asyncio.run(consult(request, TripContext(), today=TODAY))
    return answer, prefs, llm


def test_consult_asks_with_llm_chips(monkeypatch) -> None:
    answer, prefs, _ = run_consult(
        monkeypatch,
        sentences=["Bạn muốn chỗ yên tĩnh hay sôi động nè?"],
        prefs={"vibe": ["quiet"]},
        chips=["Yên tĩnh thôi", "Biển nha"],
    )
    assert answer.kind == "answer"
    assert answer.text == "Bạn muốn chỗ yên tĩnh hay sôi động nè?"
    assert answer.suggestions == ["Yên tĩnh thôi", "Biển nha"]
    assert prefs == TravelPrefs(vibe=["quiet"])
    assert answer.facts == [{"type": "consult", "hasSuggestions": False, "destinationIds": []}]


def test_consult_suggests_and_code_builds_chips(monkeypatch) -> None:
    answer, _, _ = run_consult(
        monkeypatch,
        sentences=["Quy Nhơn có Eo Gió và bãi biển hoang sơ nè."],
        destination_ids=["quy-nhon", "nha-trang"],
        chips=["chip của LLM bị bỏ"],
        is_done_asking=True,
    )
    assert answer.suggestions == [
        "Xem reel Quy Nhơn",
        "Tìm phòng Quy Nhơn",
        "Lên lịch trình Quy Nhơn",
        "Nơi khác nha",
    ]
    assert answer.facts[0]["hasSuggestions"] is True
    assert answer.facts[0]["destinationIds"] == ["quy-nhon", "nha-trang"]


def test_consult_drops_unknown_ids(monkeypatch) -> None:
    answer, _, _ = run_consult(
        monkeypatch,
        sentences=["Quy Nhơn có Eo Gió nè."],
        destination_ids=["atlantis", "quy-nhon"],
    )
    assert answer.facts[0]["destinationIds"] == ["quy-nhon"]
    assert answer.suggestions[0] == "Xem reel Quy Nhơn"


def test_consult_drops_sentence_with_place_outside_catalog(monkeypatch) -> None:
    answer, _, _ = run_consult(
        monkeypatch,
        sentences=["Đi Bali đi bạn.", "Quy Nhơn có Eo Gió nè."],
        destination_ids=["quy-nhon"],
    )
    assert answer.text == "Quy Nhơn có Eo Gió nè."


def test_consult_drops_single_word_place_outside_catalog(monkeypatch) -> None:
    answer, _, _ = run_consult(
        monkeypatch,
        sentences=["Mình gợi ý Bali nha.", "Quy Nhơn yên tĩnh lắm nè."],
        destination_ids=["quy-nhon"],
    )
    assert answer.text == "Quy Nhơn yên tĩnh lắm nè."
    asking, _, _ = run_consult(
        monkeypatch, chips=["Biển nha", "thử Jeju xem"], sentences=["Bạn thích gì nè?"]
    )
    assert asking.suggestions == ["Biển nha"]


def test_consult_keeps_mention_of_other_catalog_place(monkeypatch) -> None:
    answer, _, _ = run_consult(
        monkeypatch,
        sentences=["Quy Nhơn gần Phú Yên, đi kết hợp được nè."],
        destination_ids=["quy-nhon"],
    )
    assert answer.text == "Quy Nhơn gần Phú Yên, đi kết hợp được nè."


def test_consult_keeps_place_user_named(monkeypatch) -> None:
    answer, _, _ = run_consult(
        monkeypatch,
        message="muốn đi Bali",
        sentences=["Bali thì Tripi chưa hỗ trợ, trong nước có Phú Quốc nè."],
        destination_ids=["phu-quoc"],
    )
    assert answer.text == "Bali thì Tripi chưa hỗ trợ, trong nước có Phú Quốc nè."


def test_consult_all_dropped_uses_fallback(monkeypatch, caplog) -> None:
    with caplog.at_level(logging.INFO):
        answer, _, _ = run_consult(monkeypatch, sentences=["Đi Bali đi bạn."], chips=["Biển nha"])
    expected = fallback_consult_answer()
    assert (answer.text, answer.suggestions) == (expected.text, expected.suggestions)
    assert answer.facts == [{"type": "consult", "fallback": True, "hasSuggestions": False}]
    assert "chat.consult.fallback" in caplog.text


def test_consult_input_masks_pii_and_has_catalog(monkeypatch) -> None:
    _, _, llm = run_consult(monkeypatch, message="gọi 0912345678 giúp mình, đi đâu chill")
    payload = json.loads(llm.user)
    assert "0912345678" not in llm.user
    assert {entry["id"] for entry in payload["catalog"]} == set(destinations_by_id())
    assert payload["currentMonth"] == 11


def test_consult_raises_on_cut_output(monkeypatch) -> None:
    llm = ScriptedConsultLlm(finish_reason="length")
    monkeypatch.setattr(consultant, "get_role_llm", lambda role: llm)
    request = ChatRequest(conversation_id=uuid4(), message="đi đâu chill")
    with pytest.raises(ValueError):
        asyncio.run(consult(request, TripContext(), today=TODAY))


def test_consult_output_schema_builds_with_nested_prefs() -> None:
    schema = strict_json_schema(ConsultOutput)
    prefs = schema["$defs"]["TravelPrefs"]
    assert set(prefs["required"]) == set(prefs["properties"])
    assert set(schema["required"]) == set(ConsultOutput.model_fields)
    assert "default" not in json.dumps(schema)
    # what the LLM writes (camelCase prefs) parses back
    parsed = ConsultOutput.model_validate_json(
        json.dumps(
            {
                "sentences": [],
                "prefs": {"budgetPerPerson": 2000000, "companions": "couple"},
                "destination_ids": [],
                "chips": [],
                "is_done_asking": False,
            }
        )
    )
    assert parsed.prefs.budget_per_person == 2_000_000


# ---- Turn: the consult route and what it remembers

FAKE_PREFS = TravelPrefs(terrain=["beach"])


def suggestion_answer(*, has_suggestions: bool) -> Answer:
    return Answer(
        kind="answer",
        text="Bạn thích biển nè.",
        facts=[{"type": "consult", "hasSuggestions": has_suggestions, "destinationIds": []}],
    )


def run_turn(
    consult_fn,
    *,
    trip: TripContext | None = None,
    intent: Literal["consult", "find_stay"] = "consult",
):
    calls: list[tuple[str, dict]] = []

    async def go():
        async with fake_core(calls) as core:
            turn = Turn(
                ChatRequest(conversation_id=uuid4(), message="đi đâu chill", trip=trip),
                Understanding(intent=intent),
                core=core,
                weather=FakeWeather(),
                today=TODAY,
                consult=consult_fn,
            )
            answer = await turn.answer()
            return turn, answer

    turn, answer = asyncio.run(go())
    return turn, answer, calls


def test_turn_routes_consult_without_search() -> None:
    seen = []

    async def fake_consult(request, trip):
        seen.append(trip)
        return suggestion_answer(has_suggestions=True), FAKE_PREFS

    turn, answer, calls = run_turn(fake_consult)
    assert answer.text == "Bạn thích biển nè." and len(seen) == 1
    assert calls == [] and turn.degraded == []


def test_turn_consult_none_uses_fallback() -> None:
    turn, answer, _ = run_turn(None)
    assert answer == fallback_consult_answer() and turn.degraded == []


@pytest.mark.parametrize("error", [httpx.ConnectError("down"), ValueError("cut"), TimeoutError()])
def test_turn_consult_error_degrades(error) -> None:
    async def broken(request, trip):
        raise error

    turn, answer, _ = run_turn(broken)
    assert answer == fallback_consult_answer() and "consult" in turn.degraded


def test_next_trip_merges_prefs_and_awaits_consult() -> None:
    async def fake_consult(request, trip):
        return suggestion_answer(has_suggestions=False), FAKE_PREFS

    turn, answer, _ = run_turn(fake_consult, trip=TripContext(prefs=TravelPrefs(vibe=["quiet"])))
    trip = turn.next_trip(answer)
    assert trip.prefs is not None and trip.prefs.vibe == ["quiet"]
    assert trip.prefs.terrain == ["beach"]
    assert trip.awaiting == Awaiting(intent="consult", missing="place")
    assert trip.asked is False


def test_next_trip_no_awaiting_after_suggestion() -> None:
    async def fake_consult(request, trip):
        return suggestion_answer(has_suggestions=True), FAKE_PREFS

    turn, answer, _ = run_turn(fake_consult)
    assert turn.next_trip(answer).awaiting is None


def test_stay_after_consult_still_asks_dates() -> None:
    async def fake_consult(request, trip):
        return suggestion_answer(has_suggestions=False), FAKE_PREFS

    turn, answer, _ = run_turn(fake_consult)
    memory = turn.next_trip(answer)
    _, stay, _ = run_turn(None, trip=memory, intent="find_stay")
    assert stay.kind == "clarify"


def test_next_weekend_words_win_over_this_weekend() -> None:
    message = "homestay da lat cuoi tuan sau"
    got = guard(message, intent="find_stay", place="Đà Lạt", day_ref="this_weekend")
    assert got.day_ref == "next_weekend"


def test_copied_example_query_is_replaced_by_message() -> None:
    message = "di vung tau hop thoi khong di bien, mang gi"
    copied = "gợi ý nơi đi chill"
    got = guard(message, intent="search", place="Vũng Tàu", query=copied, reel_query=copied)
    assert (got.query, got.reel_query) == (message, message)


def test_real_goi_y_query_is_kept() -> None:
    got = guard(
        "gợi ý chỗ đi chill ở đà lạt", intent="search", place="Đà Lạt", query="gợi ý nơi đi chill"
    )
    assert got.query == "gợi ý nơi đi chill"


def test_what_can_you_do_is_identity_not_consult() -> None:
    assert (
        guard("ban lam duoc gi", intent="consult", query="gợi ý nơi đi chill").intent == "identity"
    )


def test_mang_gi_is_packing() -> None:
    got = guard("di vung tau hop thoi khong di bien, mang gi", intent="search", place="Vũng Tàu")
    assert (got.intent, got.place) == ("packing", "Vũng Tàu")


def test_bay_ra_city_without_plan_is_find_flight() -> None:
    message = "3 ngày nữa mình bay ra hà nội từ sài gòn"
    plan = controller_plan(intent="change_transport", from_city="TP.HCM", to_city="Hà Nội")
    assert apply_guards(plan, message, has_reel=False).intent == "find_flight"
    planned = apply_guards(plan, message, has_reel=False, in_plan=True)
    assert planned.intent == "change_transport"


def test_len_lich_trinh_is_plan_trip() -> None:
    got = guard(
        "Lên lịch trình Đà Nẵng 3 ngày 2 đêm cuối tuần này",
        intent="search",
        place="Đà Nẵng",
        query="gợi ý nơi đến cuối tuần",
    )
    assert got.intent == "plan_trip"
    assert guard("lịch trình Phú Quốc 4n3d", intent="search", place="Phú Quốc").intent == "search"
    reel = guard("reel lịch trình đà lạt", intent="find_reel", place="Đà Lạt")
    assert reel.intent == "find_reel"


def test_goi_y_noi_den_query_is_replaced_by_message() -> None:
    message = "đi đà nẵng cuối tuần"
    got = guard(message, intent="search", place="Đà Nẵng", query="gợi ý nơi đến cuối tuần")
    assert got.query == message


def test_sort_words_are_not_price_relative() -> None:
    sort = guard(
        "xếp từ rẻ đến đắt", intent="find_stay", stay_sort="price_asc", price_relative="lower"
    )
    assert (sort.stay_sort, sort.price_relative) == ("price_asc", "none")
    cheaper = guard("tìm căn rẻ hơn", intent="find_stay", price_relative="lower")
    assert cheaper.price_relative == "lower"
    assert (
        guard("xịn hơn nữa", intent="find_stay", price_relative="higher").price_relative == "higher"
    )


def test_stated_nights_win() -> None:
    start = DayMonth(day=21, month=11)
    end = DayMonth(day=22, month=11)
    got = guard(
        "ks vung tau 21/11 2 dem cho 2 nguoi",
        intent="find_stay",
        place="Vũng Tàu",
        start=start,
        end=end,
        nights=1,
    )
    assert (got.nights, got.end) == (2, None)
    tonight = guard("ks vung tau dem nay", intent="find_stay", nights=1)
    assert tonight.nights == 1
    short = guard("ks vung tau 21/11 3n2d", intent="find_stay", start=start, nights=3)
    assert short.nights == 2


def test_copied_message_is_not_a_reel_name() -> None:
    got = guard("ngày 2 đi đâu", has_reel=True, intent="post_itinerary", reel_query="ngay 2 di dau")
    assert got.reel_query == ""
