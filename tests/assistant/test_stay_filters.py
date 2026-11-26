"""Stay filters and sorting read by the Controller (TF31): price floor, stars, sort, "đắt hơn"."""

import json
from uuid import uuid4

import pytest

from app.services.assistant.controller import apply_guards, to_understanding
from app.services.assistant.schemas import CardRef, ChatRequest, TripContext
from app.services.assistant.understand import build_understanding_input
from evals.assistant.run import TODAY, controller_plan


def test_to_understanding_reads_stay_filters():
    out = controller_plan(
        intent="find_stay",
        place="Nha Trang",
        price_min_per_night=1_000_000,
        stay_sort="price_asc",
        min_stars=4,
        price_relative="higher",
    )
    parsed = to_understanding(out, None, TODAY)
    assert parsed.price_min_per_night == 1_000_000
    assert parsed.stay_sort == "price_asc"
    assert parsed.min_stars == 4
    assert parsed.price_relative == "higher"


def test_to_understanding_drops_bad_stars_and_price():
    trip = TripContext(price_min_per_night=600_000)
    out = controller_plan(intent="find_stay", min_stars=7, price_min_per_night=0)
    parsed = to_understanding(out, trip, TODAY)
    assert parsed.min_stars is None
    assert parsed.price_min_per_night == 600_000


def test_to_understanding_falls_back_to_trip_min_filters():
    trip = TripContext(place="Nha Trang", price_min_per_night=800_000, min_stars=3)
    parsed = to_understanding(controller_plan(intent="find_stay"), trip, TODAY)
    assert parsed.price_min_per_night == 800_000
    assert parsed.min_stars == 3


def test_controller_input_has_stay_card_prices():
    trip = TripContext(
        last_cards=[
            CardRef(ref="r1", kind="stay", id="h1", title="A", price=450_000),
            CardRef(ref="r2", kind="video", id="p1", title="B"),
            CardRef(ref="r3", kind="stay", id="h2", title="C"),
        ]
    )
    request = ChatRequest(conversation_id=uuid4(), message="đắt hơn", trip=trip)
    cards = json.loads(build_understanding_input(request))["trip"]["lastCards"]
    assert cards == [
        {"ref": "r1", "kind": "stay", "price": 450000},
        {"ref": "r2", "kind": "video"},
        {"ref": "r3", "kind": "stay"},
    ]


@pytest.mark.parametrize(
    "message",
    ["tìm căn đắt hơn", "xếp từ rẻ nhất đến đắt nhất", "có căn nào 4 sao trở lên không"],
)
def test_guards_keep_find_stay_for_filter_messages(message):
    out = controller_plan(intent="find_stay", place="Nha Trang", price_relative="higher")
    guarded = apply_guards(out, message, has_reel=False, has_options=True)
    assert guarded.intent == "find_stay"
    assert guarded.price_relative == "higher"
