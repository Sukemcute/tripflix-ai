"""Moving a stop edits the draft, keeps service lines and grounds edit claims."""

import asyncio
import json
from datetime import date
from uuid import uuid4

import pytest

from app.clients.llm.base import LlmResult
from app.services.assistant import responder
from app.services.assistant.controller import apply_guards, move_from_message, to_understanding
from app.services.assistant.route import estimate_leg
from app.services.assistant.schemas import (
    Answer,
    ChatRequest,
    DraftChoice,
    DraftStop,
    DraftTransport,
    TripContext,
    Understanding,
)
from app.services.assistant.skills.plan import TripPlanner
from app.services.assistant.turn import Turn
from app.services.assistant.verifier import EDIT_CLAIM, verify
from app.services.summary.vi_text import normalize_text
from evals.assistant.run import FakeWeather, controller_plan, fake_core
from tests.assistant.test_trip_planner import FakePlaces

MESSAGE = "Tôi muốn đi cầu rồng trước rồi mới sang bảo tàng nghệ thuật điêu khắc, xếp lại"
CLAIM = "Tripi đổi lại rồi nha: Cầu Rồng trước, rồi mới tới Bảo tàng…"


def run(parsed, trip, *, message="..."):
    calls = []

    async def go():
        async with fake_core(calls) as core:
            request = ChatRequest(conversation_id=uuid4(), message=message, trip=trip)
            turn = Turn(
                request,
                parsed,
                core=core,
                weather=FakeWeather(),
                today=date(2026, 11, 19),
                places=FakePlaces(),
            )
            answer = await turn.answer()
            return answer, turn.planned_trip or trip, calls

    return asyncio.run(go())


def draft():
    def stop(id, name, lat, lng, slot):
        return DraftStop(id=id, name=name, lat=lat, lng=lng, slot=slot)

    return TripContext(
        place="Đà Nẵng",
        origin_city="TP.HCM",
        date_from=date(2026, 11, 21),
        date_to=date(2026, 11, 22),
        stay=DraftChoice(source="tripflix", id="h1", name="Khách sạn", lat=16, lng=108),
        days=[
            [
                stop(
                    "museum", "Bảo tàng Nghệ thuật Điêu khắc Chăm Đà Nẵng", 16.01, 108.01, "chiều"
                ),
                stop("dragon", "Cầu Rồng", 16.02, 108.02, "chiều"),
                stop("marina", "Marina Coffee", 16.03, 108.03, "tối"),
            ],
            [stop("market", "Chợ Hàn", 16.04, 108.04, "sáng")],
        ],
    )


def move(trip, **fields):
    if fields.get("anchor_name"):
        relation = "trước" if fields.get("placement") == "before" else "sau"
        message = f"Cầu Rồng {relation} {fields['anchor_name']}"
    else:
        message = f"chuyển Cầu Rồng sang ngày {fields.get('target_day', 1)}"
    return run(
        Understanding(intent="move_stop", stop_name="Cầu Rồng", **fields), trip, message=message
    )


@pytest.mark.parametrize(
    ("placement", "stop", "anchor", "order"),
    [
        ("before", "Cầu Rồng", "bảo tàng nghệ thuật điêu khắc", ["dragon", "museum", "marina"]),
        ("after", "bảo tàng nghệ thuật điêu khắc", "Cầu Rồng", ["dragon", "museum", "marina"]),
    ],
)
def test_move_before_or_after_in_same_slot(placement, stop, anchor, order):
    trip = draft()
    answer, changed, calls = run(
        Understanding(intent="move_stop", stop_name=stop, anchor_name=anchor, placement=placement),
        trip,
        message=f"{stop} {'trước' if placement == 'before' else 'sau'} {anchor}",
    )
    assert [s.id for s in changed.days[0]] == order
    assert answer.cards[0].kind == "itinerary" and answer.edit_applied
    assert "Đã chuyển" in answer.text and calls == []
    assert changed.ops[-1].stop and changed.ops[-1].stop.slot == "chiều"
    assert trip == draft()


@pytest.mark.parametrize(
    ("fields", "day", "slot"),
    [
        ({"target_day": 2, "target_slot": "sáng"}, 1, "sáng"),
        ({"target_slot": "tối"}, 0, "tối"),
        ({"anchor_name": "Chợ Hàn", "placement": "after"}, 1, "sáng"),
        ({"target_day": 2}, 1, "chiều"),
    ],
)
def test_move_to_another_day_or_end_of_slot(fields, day, slot):
    answer, changed, _ = move(draft(), **fields)
    assert answer.edit_applied
    assert changed.days[day][-1].id == "dragon"
    assert changed.days[day][-1].slot == slot


@pytest.mark.parametrize(
    ("arrival", "departure", "day", "slot"),
    [
        ("14:30", None, 1, "sáng"),
        ("18:00", None, 1, "chiều"),
        (None, "17:00", 2, "tối"),
        (None, "15:00", 2, "chiều"),
    ],
)
def test_flight_windows_block_move_without_changing_trip(arrival, departure, day, slot):
    trip = draft()
    if arrival:
        trip.transport = DraftTransport(mode="flight", summary="Vé đi", arrive_time=arrival)
    if departure:
        trip.return_transport = DraftTransport(
            mode="flight", summary="Vé về", depart_time=departure
        )
    original = trip.model_copy(deep=True)
    answer, changed, _ = move(trip, target_day=day, target_slot=slot)
    assert answer.kind == "clarify" and "Khung giờ bay" in answer.text
    assert changed == original and trip == original and not answer.edit_applied


def test_anchor_slot_is_also_checked_against_flight_window():
    trip = draft()
    trip.transport = DraftTransport(mode="flight", summary="Vé đi", arrive_time="18:00")
    answer, changed, _ = move(trip, anchor_name="Bảo tàng", placement="before")
    assert answer.kind == "clarify" and changed == trip


@pytest.mark.parametrize(
    "fields",
    [
        {"stop_name": "Không có", "anchor_name": "Cầu Rồng", "placement": "before"},
        {"stop_name": "Cầu Rồng", "anchor_name": "Không có", "placement": "before"},
        {"stop_name": "Cầu Rồng", "target_day": 3},
        {"stop_name": "Cầu Rồng"},
    ],
)
def test_invalid_move_clarifies_and_does_not_change_draft(fields):
    trip = draft()
    answer, changed, _ = run(Understanding(intent="move_stop", **fields), trip)
    assert answer.kind == "clarify" and changed == trip and not answer.edit_applied


def test_no_plan_clarifies():
    answer, trip, _ = move(TripContext(), target_day=1)
    assert answer.kind == "clarify" and "chưa có lộ trình" in answer.text
    assert trip.days == [] and not answer.edit_applied


def test_no_op_does_not_claim_a_successful_edit():
    trip = draft()
    answer, changed, _ = move(trip, anchor_name="Marina Coffee", placement="before")
    # The anchor's evening slot differs, so this first move is real.
    assert answer.edit_applied
    again, unchanged, _ = move(changed, anchor_name="Marina Coffee", placement="before")
    assert again.kind == "clarify" and not again.edit_applied and unchanged == changed


def test_undo_restores_original_day_position_and_slot():
    original = draft()
    _, changed, _ = move(original, target_day=2, target_slot="sáng")
    answer, restored, _ = run(Understanding(intent="undo"), changed)
    assert restored.days == original.days and restored.ops == [] and answer.edit_applied


def test_service_lines_stay_in_place_and_distances_are_recomputed():
    trip = draft()
    trip.transport = DraftTransport(
        mode="flight", summary="Vé đi", from_airport="SGN", to_airport="DAD", depart_time="08:00"
    )
    trip.return_transport = DraftTransport(
        mode="flight", summary="Vé về", from_airport="DAD", to_airport="SGN", depart_time="21:00"
    )

    async def render():
        async with fake_core() as core:
            return await TripPlanner(
                core, FakePlaces(), FakeWeather(), date(2026, 11, 19), trip
            )._render()

    before = asyncio.run(render())
    answer, changed, _ = move(trip, anchor_name="Bảo tàng", placement="before")
    lines = answer.cards[0].lines or []
    original_lines = before.cards[0].lines or []
    assert [line for line in lines if line.service] == [
        line for line in original_lines if line.service
    ]
    assert [line.service for line in lines[:2]] == ["flight", "stay"]
    assert [line.service for line in lines[-2:]] == ["stay", "flight"]
    leg = estimate_leg((16, 108), (16.02, 108.02))
    assert lines[2].detail == f"Cầu Rồng · khoảng {leg.km:g} km, {leg.minutes} phút"
    assert lines[2].detail != original_lines[2].detail
    assert changed.days[0][0].id == "dragon"


@pytest.mark.parametrize("raw_intent", ["plan_trip", "search", "clarify", "move_stop"])
def test_controller_guard_prioritizes_move_and_preserves_slots(raw_intent):
    fixed = apply_guards(
        controller_plan(
            intent=raw_intent,
            stop_name="Cầu Rồng",
            anchor_name="bảo tàng nghệ thuật điêu khắc",
            placement="before",
        ),
        MESSAGE,
        has_reel=False,
        in_plan=True,
    )
    parsed = to_understanding(fixed, draft(), date(2026, 11, 19))
    assert parsed.intent == "move_stop" and parsed.placement == "before"
    assert parsed.anchor_name == "bảo tàng nghệ thuật điêu khắc"


@pytest.mark.parametrize(
    "fields",
    [
        {"target_day": 2},
        {"target_slot": "tối"},
    ],
)
def test_controller_copies_move_day_and_slot(fields):
    out = controller_plan(intent="move_stop", stop_name="Marina Coffee", **fields)
    parsed = to_understanding(out, draft(), date(2026, 11, 19))
    assert all(getattr(parsed, key) == value for key, value in fields.items())


@pytest.mark.parametrize("edited", [False, True])
def test_exact_false_claim_is_dropped_only_without_successful_edit(edited):
    facts = [{"names": ["Cầu Rồng", "Bảo tàng"]}]
    kept, dropped = verify([CLAIM], facts, set(), MESSAGE, edit_applied=edited)
    assert kept == ([CLAIM] if edited else [])
    assert dropped == ({} if edited else {"V9_unapplied_edit": 1})


@pytest.mark.parametrize(
    "sentence",
    [
        "Đã chuyển điểm rồi nha.",
        "Mình đã bỏ điểm đó.",
        "Tripi xếp lại rồi nha.",
        "Mình sửa lại rồi.",
        "Đã thêm điểm nha.",
        "Mình vừa đổi thứ tự.",
    ],
)
def test_other_past_edit_claims_need_a_successful_edit(sentence):
    kept, dropped = verify([sentence], [], set(), "xếp lại")
    assert kept == [] and dropped == {"V9_unapplied_edit": 1}


@pytest.mark.parametrize(
    ("sentence", "is_edit_claim"),
    [
        (
            "Ngày 20/11 mình xếp lịch trình Đà Nẵng 2 ngày cho bạn rồi nha, có cả vé 11:00.",
            False,
        ),
        ("Nhớ bỏ áo mưa vào vali rồi hẵng đi nha.", False),
        ("Mình tìm thêm vài chỗ ở rồi nè.", False),
        ("Tripi đổi lại rồi nha: Cầu Rồng trước.", True),
        ("Lộ trình Đà Nẵng 2 ngày đây nè, xếp từ Hilary Hotel.", False),
    ],
)
def test_edit_claim_does_not_match_initial_planning_or_advice(sentence, is_edit_claim):
    assert bool(EDIT_CLAIM.search(normalize_text(sentence))) is is_edit_claim
    kept, dropped = verify([sentence], [{"text": sentence}], set(), "", edit_applied=False)
    assert kept == ([] if is_edit_claim else [sentence])
    assert dropped == ({"V9_unapplied_edit": 1} if is_edit_claim else {})


def test_completed_move_claim_is_kept_after_a_real_edit():
    sentence = "Đã chuyển Cầu Rồng lên trước Bảo tàng…"
    kept, dropped = verify(
        [sentence], [{"names": ["Cầu Rồng", "Bảo tàng"]}], set(), "", edit_applied=True
    )
    assert kept == [sentence] and dropped == {}


def test_first_plan_turn_keeps_responder_initial_planning_sentence(monkeypatch):
    sentence = "Mình xếp lịch trình Đà Nẵng 2 ngày cho bạn rồi nha."
    message = "lên lịch Đà Nẵng 2 ngày"

    class FakeLlm:
        async def agenerate(self, system, user, schema):
            assert json.loads(user)["editApplied"] is False
            return LlmResult(json.dumps({"sentences": [sentence]}), "fake", 1, 1)

    monkeypatch.setattr(responder, "get_role_llm", lambda role: FakeLlm())
    answer, _, _ = run(
        Understanding(
            intent="plan_trip",
            place="Đà Nẵng",
            from_city="TP.HCM",
            nights=1,
            check_in=date(2026, 11, 20),
            check_out=date(2026, 11, 21),
        ),
        TripContext(),
        message=message,
    )
    assert answer.cards[0].kind == "itinerary" and not answer.edit_applied
    request = ChatRequest(conversation_id=uuid4(), message=message)
    sentences, _ = asyncio.run(responder.respond(request, answer))
    assert sentences is not None and sentence in sentences


def test_old_draft_operation_still_parses():
    trip = TripContext.model_validate({"v": 1, "ops": [{"op": "remove_stop"}]})
    assert trip.ops[0].op == "remove_stop" and trip.return_transport is None


@pytest.mark.parametrize("edited", [False, True])
def test_responder_receives_and_enforces_code_edit_result(monkeypatch, edited):
    class FakeLlm:
        async def agenerate(self, system, user, schema):
            assert json.loads(user)["editApplied"] is edited
            return LlmResult(json.dumps({"sentences": [CLAIM]}), "fake", 1, 1)

    monkeypatch.setattr(responder, "get_role_llm", lambda role: FakeLlm())
    request = ChatRequest(conversation_id=uuid4(), message=MESSAGE)
    answer = Answer(
        kind="answer",
        text="Lộ trình hiện tại.",
        edit_applied=edited,
        facts=[{"names": ["Cầu Rồng", "Bảo tàng"]}],
    )
    sentences, _ = asyncio.run(responder.respond(request, answer))
    assert sentences == ([CLAIM] if edited else None)


def test_numbered_plan_day_does_not_change_travel_dates_or_destination():
    fixed = apply_guards(
        controller_plan(
            intent="plan_trip",
            stop_name="Chợ Hàn",
            target_day=2,
            place="Chợ Hàn",
            start={"day": 2, "month": 12},
            nights=2,
        ),
        "chuyển chợ Hàn sang ngày 2",
        has_reel=False,
        in_plan=True,
    )
    parsed = to_understanding(fixed, draft(), date(2026, 11, 19))
    assert parsed.intent == "move_stop" and parsed.target_day == 2
    assert parsed.place == "Đà Nẵng" and parsed.check_in == date(2026, 11, 21)
    assert parsed.check_out == date(2026, 11, 22)


@pytest.mark.parametrize("intent", ["remove_stop", "undo"])
def test_existing_edit_operations_mark_only_a_real_change(intent):
    trip = draft()
    if intent == "undo":
        _, trip, _ = move(trip, anchor_name="Bảo tàng", placement="before")
    answer, _, _ = run(Understanding(intent=intent, stop_name="Cầu Rồng"), trip)
    assert answer.edit_applied


DALAT_MESSAGES = [
    "Đổi lịch đi, tôi muốn đi Khu du lịch Thung Lũng trước Thiên Vương cổ sát",
    "đổi ngày 1 Đà Lạt: Thung Lũng Tình Yêu trước, rồi Chùa Tàu",
]


def dalat_draft():
    def stop(id, name, lat, slot):
        return DraftStop(id=id, name=name, lat=lat, lng=108.45, slot=slot)

    return TripContext(
        place="Đà Lạt",
        origin_city="TP.HCM",
        date_from=date(2026, 11, 20),
        date_to=date(2026, 11, 21),
        days=[
            [
                stop("p1", "Thiên Vương Cổ Sát (Chùa Tàu)", 11.95, "chiều"),
                stop("p2", "Khu du lịch Thung Lũng Tình Yêu", 11.98, "chiều"),
                stop("p3", "German House", 11.94, "tối"),
            ],
            [stop("p4", "Bảo Tàng Lâm Đồng", 11.93, "sáng")],
        ],
    )


@pytest.mark.parametrize(
    ("message", "placement"),
    [
        *[(text, "before") for text in DALAT_MESSAGES],
        ("Thung Lũng rồi mới Chùa Tàu", "before"),
        ("Thung Lũng rồi mới sang Chùa Tàu", "before"),
        ("Thung Lũng sau Thiên Vương Cổ Sát", "after"),
    ],
)
def test_message_aliases_override_wrong_llm_anchor(message, placement):
    trip = dalat_draft()
    parsed = to_understanding(
        controller_plan(
            intent="move_stop",
            stop_name="Khu du lịch Thung Lũng Tình Yêu",
            anchor_name="German House",
            placement="before",
        ),
        trip,
        date(2026, 11, 19),
        message=message,
    )
    assert parsed.intent == "move_stop" and parsed.placement == placement
    assert parsed.anchor_name != "German House"
    answer, changed, calls = run(parsed, trip, message=message)
    assert [s.id for s in changed.days[0]] == (
        ["p2", "p1", "p3"] if placement == "before" else ["p1", "p2", "p3"]
    )
    assert changed.days[0][0].slot == "chiều" and not calls
    assert answer.kind == ("answer" if placement == "before" else "clarify")


def test_da_nang_message_resolves_the_actual_points_without_llm_names():
    trip = draft()
    move = move_from_message(MESSAGE, trip)
    assert move is not None and move["placement"] == "before"
    parsed = to_understanding(
        controller_plan(intent="search"), trip, date(2026, 11, 19), message=MESSAGE
    )
    answer, changed, calls = run(parsed, trip, message=MESSAGE)
    assert [s.id for s in changed.days[0]] == ["dragon", "museum", "marina"]
    assert answer.edit_applied and not calls


@pytest.mark.parametrize(
    "message",
    ["Thung Lũng", "Thung Lũng và Chùa Tàu", "Thung Lũng trước Chùa Tàu rồi German House"],
)
def test_message_parser_does_not_guess_without_two_distinct_ordered_points(message):
    assert move_from_message(message, dalat_draft()) is None


@pytest.mark.parametrize("message", ["Tôi muốn đổi lịch trình", "sửa lịch", "đổi lịch đi"])
def test_unspecified_edit_asks_before_rebuilding(message):
    trip = dalat_draft()
    parsed = to_understanding(
        controller_plan(intent="plan_trip", place="Đà Lạt"),
        trip,
        date(2026, 11, 19),
        message=message,
    )
    assert parsed.intent == "clarify"
    answer, changed, calls = run(parsed, trip, message=message)
    assert answer.kind == "clarify" and not answer.cards and not calls
    assert answer.suggestions == ["Đổi thứ tự điểm", "Bỏ một điểm", "Đổi chỗ ở", "Đổi ngày đi"]
    assert changed == trip and not answer.edit_applied


@pytest.mark.parametrize("placement", ["before", "after"])
def test_noop_compares_ids_and_slots_despite_fields_set(placement):
    a = DraftStop(id="a", name="Điểm Một", lat=11, lng=108)
    b = DraftStop(id="b", name="Điểm Hai", lat=11.1, lng=108)
    assert a.model_fields_set != a.model_copy(update={"slot": a.slot}).model_fields_set
    trip = TripContext(place="Đà Lạt", days=[[a, b] if placement == "before" else [b, a]])
    original = trip.model_dump()
    notes = []

    async def go():
        async with fake_core() as core:
            planner = TripPlanner(
                core, FakePlaces(), FakeWeather(), date(2026, 11, 19), trip, notes
            )
            return await planner.move_stop("Điểm Một", anchor_name="Điểm Hai", placement=placement)

    answer = asyncio.run(go())
    assert (
        answer.kind == "clarify"
        and f"đã ở {'trước' if placement == 'before' else 'sau'}" in answer.text
    )
    assert trip.model_dump() == original and not trip.ops and not notes and not answer.edit_applied


def test_dalat_repeated_move_is_noop_after_first_edit():
    trip = dalat_draft()
    _, changed, _ = run(Understanding(intent="plan_trip"), trip, message=DALAT_MESSAGES[0])
    answer, unchanged, calls = run(
        Understanding(intent="plan_trip"), changed, message=DALAT_MESSAGES[1]
    )
    assert answer.kind == "clarify" and "đã ở trước" in answer.text
    assert unchanged.days == changed.days and unchanged.ops == changed.ops and not calls
    assert not answer.edit_applied


@pytest.mark.parametrize("message", ["hãy làm toán cho tôi", "tính giúp tôi", "giải giúp bài toán"])
def test_math_cues_do_not_fall_through_to_search(message):
    fixed = apply_guards(controller_plan(intent="search"), message, has_reel=False)
    assert fixed.intent == "refusal"


# "Thung Lũng" (p2) should end up before or after "Chùa Tàu" (p1); day 1 starts p1, p2, p3.
VISIT_ORDER = [
    ("Tôi muốn đi Thung Lũng trước Chùa Tàu", True),
    ("đi Chùa Tàu sau Thung Lũng", True),
    ("Thung Lũng rồi Chùa Tàu", True),
    ("Thung Lũng xong rồi mới qua Chùa Tàu", True),
    ("đi Thung Lũng, sau đó tới Chùa Tàu", True),
    ("sau khi đi Thung Lũng thì ghé Chùa Tàu", True),
    ("trước Chùa Tàu thì đi Thung Lũng", True),
    ("đầu tiên đi Thung Lũng rồi Chùa Tàu", True),
    ("Chùa Tàu sau khi đi Thung Lũng", True),
    ("đổi chỗ Chùa Tàu và Thung Lũng", True),
    ("Chùa Tàu trước Thung Lũng", False),
    ("Thung Lũng sau Chùa Tàu", False),
    ("Chùa Tàu rồi mới tới Thung Lũng", False),
]


@pytest.mark.parametrize(("message", "valley_first"), VISIT_ORDER)
def test_order_words_decide_the_visit_order(message, valley_first):
    trip = dalat_draft()
    parsed = to_understanding(
        controller_plan(intent="move_stop", stop_name="German House", anchor_name="Bảo Tàng"),
        trip,
        date(2026, 11, 19),
        message=message,
    )
    answer, changed, calls = run(parsed, trip, message=message)
    order = [s.id for s in changed.days[0]]
    assert (order.index("p2") < order.index("p1")) is valley_first, (message, order)
    assert order[-1] == "p3" and not calls
    # Already in that order: say so, never claim an edit.
    assert answer.edit_applied is valley_first


@pytest.mark.parametrize("message", ["Thung Lũng và Chùa Tàu", "Thung Lũng, Chùa Tàu"])
def test_two_points_without_order_words_are_not_guessed(message):
    assert move_from_message(message, dalat_draft()) is None


@pytest.mark.parametrize(
    ("message", "name"),
    [
        ("bỏ Tượng Chúa đi", "Tượng Chúa"),
        ("không đi Tượng Chúa nữa", "Tượng Chúa"),
        ("xoá Bảo tàng khỏi lịch", "Bảo tàng"),
        ("bỏ Bãi Sau đi", "Bãi Sau"),
    ],
)
def test_delete_named_stop_overrides_model_move(message, name):
    trip = draft()
    trip.days[0][0] = trip.days[0][0].model_copy(update={"name": name})
    parsed = to_understanding(
        controller_plan(intent="move_stop", stop_name=name, anchor_name="Marina Coffee"),
        trip,
        date(2026, 11, 19),
        message=message,
    )
    assert parsed.intent == "remove_stop"
    assert parsed.stop_name == normalize_text(name)
    answer, changed, calls = run(parsed, trip, message=message)
    assert answer.kind == "answer"
    assert all(stop.id != "museum" for day in changed.days for stop in day)
    assert not calls


@pytest.mark.parametrize(
    "message",
    [
        "bỏ qua Tượng Chúa, đi Bãi Sau trước",
        "chuyển Tượng Chúa sang ngày 2",
        "đổi Tượng Chúa sang buổi tối",
    ],
)
def test_delete_guard_does_not_override_order_or_day_moves(message):
    trip = draft()
    trip.days[0][0] = trip.days[0][0].model_copy(update={"name": "Tượng Chúa"})
    trip.days[0][1] = trip.days[0][1].model_copy(update={"name": "Bãi Sau"})
    parsed = to_understanding(
        controller_plan(intent="move_stop", stop_name="Tượng Chúa"),
        trip,
        date(2026, 11, 19),
        message=message,
    )
    assert parsed.intent == "move_stop"


@pytest.mark.parametrize(
    ("message", "removes"),
    [
        ("đi bộ ra Cầu Rồng ngắm pháo hoa", False),
        ("dạo bờ biển gần Cầu Rồng nha", False),
        ("đi bo bo ra cau rong", False),
        ("đi bộ Cầu Rồng", False),
        ("bỏ Cầu Rồng đi", True),
        ("bo cau rong di", True),
        ("không đi Cầu Rồng nữa", True),
        ("xoá Cầu Rồng khỏi lịch", True),
        ("BO\u0309 Cầu Rồng đi", True),
    ],
)
def test_delete_guard_preserves_accents_and_requires_adjacent_ascii_verb(message, removes):
    trip = draft()
    trip.days[1][0] = trip.days[1][0].model_copy(update={"name": "Bãi biển Mỹ Khê"})
    parsed = to_understanding(
        controller_plan(intent="search", query=message),
        trip,
        date(2026, 11, 19),
        message=message,
    )
    assert (parsed.intent == "remove_stop") is removes
    if removes:
        assert parsed.stop_name == "cau rong"
        answer, changed, calls = run(parsed, trip, message=message)
        assert answer.edit_applied
        assert all(stop.id != "dragon" for day in changed.days for stop in day)
        assert not calls
