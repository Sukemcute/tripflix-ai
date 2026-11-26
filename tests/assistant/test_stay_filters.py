"""Stay filters and sorting read by the Controller (TF31): price floor, stars, sort, "đắt hơn"."""

import json
from uuid import uuid4

import pytest

from app.services.assistant.controller import apply_guards, to_understanding
from app.services.assistant.schemas import CardRef, ChatRequest, TripContext, Understanding
from app.services.assistant.skills.stay import refine_stay_filters
from app.services.assistant.understand import build_understanding_input
from app.services.assistant.verifier import verify
from evals.assistant.run import TODAY, controller_plan
from tests.assistant.test_report_regressions import IN_5, PLACE, FakeCore, dm, plan, run_turn


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


# ---- "đắt hơn" / "rẻ hơn" become price bounds, filters reach Core


def shown_stays(*prices: int | None) -> list[CardRef]:
    return [
        CardRef(ref=f"r{i}", kind="stay", id=f"h{i}", title="Khách sạn", price=price)
        for i, price in enumerate(prices, 1)
    ]


def test_higher_drops_remembered_cap():
    understood = Understanding(
        intent="find_stay", price_relative="higher", price_max_per_night=500_000
    )
    refined = refine_stay_filters(
        understood,
        shown_stays(300_000, 450_000),
        remembered=TripContext(price_max_per_night=500_000),
    )
    assert refined.price_min_per_night == 450_001
    assert refined.price_max_per_night is None
    assert refined.stay_sort == "price_asc"
    assert understood.price_min_per_night is None and understood.price_max_per_night == 500_000


def test_higher_keeps_explicit_cap_above_new_floor():
    understood = Understanding(
        intent="find_stay", price_relative="higher", price_max_per_night=2_000_000
    )
    refined = refine_stay_filters(understood, shown_stays(450_000), remembered=TripContext())
    assert (refined.price_min_per_night, refined.price_max_per_night) == (450_001, 2_000_000)


def test_lower_sets_cap_below_cheapest():
    understood = Understanding(intent="find_stay", price_relative="lower")
    refined = refine_stay_filters(
        understood, shown_stays(300_000, 450_000), remembered=TripContext()
    )
    assert refined.price_max_per_night == 299_999
    assert refined.stay_sort == "price_desc"


def test_relative_without_prices_only_sorts():
    refined = refine_stay_filters(
        Understanding(intent="find_stay", price_relative="higher"),
        shown_stays(None),
        remembered=TripContext(),
    )
    assert refined.stay_sort == "price_desc" and refined.price_min_per_night is None


def test_lower_drops_remembered_floor():
    understood = Understanding(
        intent="find_stay", price_relative="lower", price_min_per_night=450_001
    )
    refined = refine_stay_filters(
        understood,
        shown_stays(450_001, 600_000),
        remembered=TripContext(price_min_per_night=450_001),
    )
    assert refined.price_min_per_night is None and refined.price_max_per_night == 450_000


def test_stay_search_sends_filters_to_core():
    core = FakeCore(PLACE | {"/api/stays": {"items": []}})
    run_turn(
        plan(
            intent="find_stay",
            place="Nha Trang",
            start=dm(IN_5),
            nights=1,
            price_min_per_night=1_000_000,
            min_stars=4,
            stay_sort="price_asc",
        ),
        core,
    )
    params = dict(core.calls)["/api/stays"]
    assert (params["priceMin"], params["minStars"], params["sort"]) == ("1000000", "4", "price")
    core = FakeCore(PLACE | {"/api/stays": {"items": []}})
    run_turn(plan(intent="find_stay", place="Nha Trang", start=dm(IN_5), nights=1), core)
    assert "sort" not in dict(core.calls)["/api/stays"]


def test_stay_search_rechecks_floor_and_stars():
    items = [
        {"hotelId": "cheap", "name": "Rẻ", "unitPrice": 900_000, "totalPrice": 900_000, "stars": 4},
        {
            "hotelId": "low",
            "name": "Ba sao",
            "unitPrice": 1_500_000,
            "totalPrice": 1_500_000,
            "stars": 3,
        },
        {
            "hotelId": "ok",
            "name": "Tốt",
            "unitPrice": 1_600_000,
            "totalPrice": 1_600_000,
            "stars": 4,
        },
    ]
    core = FakeCore(PLACE | {"/api/stays": {"items": items}})
    answer, _ = run_turn(
        plan(
            intent="find_stay",
            place="Nha Trang",
            start=dm(IN_5),
            nights=1,
            price_min_per_night=1_000_000,
            min_stars=4,
        ),
        core,
    )
    assert [card.id for card in answer.cards] == ["ok"]


def test_next_trip_keeps_card_prices_and_filters():
    items = [{"hotelId": "h1", "name": "A", "unitPrice": 1_200_000, "totalPrice": 1_200_000}]
    core = FakeCore(PLACE | {"/api/stays": {"items": items}})
    answer, turn = run_turn(
        plan(
            intent="find_stay",
            place="Nha Trang",
            start=dm(IN_5),
            nights=1,
            price_min_per_night=1_000_000,
            min_stars=4,
        ),
        core,
    )
    memory = turn.next_trip(answer)
    assert answer.cards[0].price_from is not None
    assert memory.last_cards[0].price == int(answer.cards[0].price_from)
    assert (memory.price_min_per_night, memory.min_stars) == (1_000_000, 4)


def test_turn_higher_after_capped_search():
    core = FakeCore(PLACE | {"/api/stays": {"items": []}})
    answer, _ = run_turn(
        plan(
            intent="find_stay", place="Vũng Tàu", start=dm(IN_5), nights=1, price_relative="higher"
        ),
        core,
        trip=TripContext(
            place="Vũng Tàu",
            price_max_per_night=500_000,
            last_cards=shown_stays(450_000),
        ),
    )
    params = dict(core.calls)["/api/stays"]
    assert params["priceMin"] == "450001" and "priceMax" not in params
    assert answer.kind == "no_result"
    assert "đắt hơn" in answer.text and "450.000đ" in answer.text
    assert answer.suggestions == ["Xem căn rẻ hơn", "Đổi ngày"]


def stay_facts(sort: str) -> list[dict]:
    return [
        {
            "ref": "r1",
            "kind": "stay",
            "title": "Khách sạn Biển Xanh",
            "pricePerNight": 450_000,
            "priceText": "450.000đ",
            "stars": 3,
            "rating": 4.2,
        },
        {
            "type": "stay_filter",
            "sort": sort,
            "priceMin": None,
            "priceMax": None,
            "minStars": None,
            "relative": "none",
            "shownBoundText": None,
        },
    ]


def test_stay_answer_facts_have_prices_and_filter():
    items = [
        {
            "hotelId": "h1",
            "name": "Khách sạn Biển Xanh",
            "unitPrice": 450_000,
            "totalPrice": 450_000,
            "stars": 3,
            "rating": {"average": 4.2, "count": 78},
        }
    ]
    core = FakeCore(PLACE | {"/api/stays": {"items": items}})
    answer, _ = run_turn(
        plan(
            intent="find_stay",
            place="Nha Trang",
            start=dm(IN_5),
            nights=1,
            stay_sort="price_asc",
            price_max_per_night=500_000,
        ),
        core,
    )
    assert answer.facts == [
        {
            "ref": "r1",
            "kind": "stay",
            "title": "Khách sạn Biển Xanh",
            "pricePerNight": 450_000,
            "priceText": "450.000đ",
            "stars": 3,
            "rating": 4.2,
        },
        {
            "type": "stay_filter",
            "sort": "price_asc",
            "priceMin": None,
            "priceMax": 500_000,
            "minStars": None,
            "relative": "none",
            "shownBoundText": None,
        },
    ]


def test_verifier_allows_cheapest_when_sorted_by_price():
    sentence = "Căn rẻ nhất là [r1], 450.000đ/đêm nè."
    kept, dropped = verify([sentence], stay_facts("price_asc"), {"r1"}, "tim phong")
    assert kept == [sentence] and not dropped


def test_verifier_drops_cheapest_on_desc_sort():
    kept, dropped = verify(
        ["Căn rẻ nhất là [r1], 450.000đ/đêm nè."], stay_facts("price_desc"), {"r1"}, "tim phong"
    )
    assert kept == [] and dropped["V4_scarcity"] == 1


def test_verifier_allows_most_expensive_on_desc_sort():
    sentence = "Căn đắt nhất là [r1], 450.000đ/đêm nè."
    kept, dropped = verify([sentence], stay_facts("price_desc"), {"r1"}, "tim phong")
    assert kept == [sentence] and not dropped
    kept, dropped = verify([sentence], stay_facts("price_asc"), {"r1"}, "tim phong")
    assert kept == [] and dropped["V4_scarcity"] == 1


def test_verifier_drops_cheapest_without_price_sort():
    kept, dropped = verify(
        ["Căn rẻ nhất là [r1], 450.000đ/đêm nè."], stay_facts("none"), {"r1"}, "tim phong"
    )
    assert kept == [] and dropped["V4_scarcity"] == 1


def test_verifier_drops_invented_price():
    kept, dropped = verify(
        ["[r1] chỉ 300.000đ/đêm nè."], stay_facts("price_asc"), {"r1"}, "tim phong"
    )
    assert kept == [] and dropped["V2_ungrounded_number"] == 1


@pytest.mark.parametrize("sentence", ["[r1] sắp hết phòng rồi.", "Nhanh tay đặt [r1] nha."])
def test_verifier_still_drops_scarcity_words(sentence):
    kept, dropped = verify([sentence], stay_facts("price_asc"), {"r1"}, "tim phong")
    assert kept == [] and dropped["V4_scarcity"] == 1


def relative_answer_text(relative: str, price: int) -> str:
    items = [{"hotelId": "h1", "name": "A", "unitPrice": price, "totalPrice": price}]
    trip = TripContext(place="Nha Trang", last_cards=shown_stays(450_000))
    core = FakeCore(PLACE | {"/api/stays": {"items": items}})
    answer, _ = run_turn(
        plan(
            intent="find_stay", place="Nha Trang", start=dm(IN_5), nights=1, price_relative=relative
        ),
        core,
        trip=trip,
    )
    assert answer.facts is not None
    fact = next(f for f in answer.facts if f.get("type") == "stay_filter")
    assert fact["shownBoundText"] is not None and fact["shownBoundText"] in answer.text
    return answer.text


def test_higher_text_names_shown_price():
    text = relative_answer_text("higher", 700_000)
    assert "đắt hơn 450.000đ/đêm" in text and "450.001" not in text


def test_lower_text_names_shown_price():
    text = relative_answer_text("lower", 300_000)
    assert "rẻ hơn 450.000đ/đêm" in text and "449.999" not in text


@pytest.mark.parametrize(("rating", "want"), [({"average": 4.1, "count": 78}, 4.1), (None, None)])
def test_stays_accept_core_rating_object(rating, want):
    items = [
        {
            "hotelId": "h1",
            "name": "A",
            "unitPrice": 450_000,
            "totalPrice": 450_000,
            "rating": rating,
        }
    ]
    core = FakeCore(PLACE | {"/api/stays": {"items": items}})
    answer, _ = run_turn(plan(intent="find_stay", place="Vũng Tàu", start=dm(IN_5), nights=1), core)
    assert answer.kind == "answer"
    assert answer.facts[0]["rating"] == want
