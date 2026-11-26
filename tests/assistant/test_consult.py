"""Destination catalog and trip preferences (consult intent, TF31)."""

import asyncio
import json
import logging
import re
from datetime import date
from typing import Any
from uuid import uuid4

import pytest

from app.clients.llm.base import LlmResult
from app.services.assistant import consultant
from app.services.assistant.consultant import (
    ConsultOutput,
    consult,
    fallback_consult_answer,
)
from app.services.assistant.controller import apply_guards
from app.services.assistant.destinations import destinations_by_id, merge_prefs
from app.services.assistant.schemas import Awaiting, ChatRequest, TravelPrefs, TripContext
from app.services.assistant.understand import build_understanding_input
from app.services.summary.schemas import strict_json_schema
from evals.assistant.run import controller_plan


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

    assert trip_of(TripContext())["prefs"] is None
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
