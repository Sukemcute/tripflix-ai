"""Destination catalog and trip preferences (consult intent, TF31)."""

import json
import re
from uuid import uuid4

import pytest

from app.services.assistant.controller import apply_guards
from app.services.assistant.destinations import destinations_by_id, merge_prefs
from app.services.assistant.schemas import Awaiting, ChatRequest, TravelPrefs, TripContext
from app.services.assistant.understand import build_understanding_input
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
