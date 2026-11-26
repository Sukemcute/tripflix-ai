"""Relative days and date questions, on a fixed Thursday (live test 2026-11-26)."""

from datetime import date

from app.services.assistant.controller import apply_guards
from app.services.assistant.schemas import Awaiting, TripContext
from evals.assistant.run import controller_plan
from tests.assistant.test_report_regressions import FakeCore, run_turn

THURSDAY = date(2026, 11, 26)


def ask(message: str, trip: TripContext | None = None, **said):
    """The Controller said `said`, guards run, then the turn: returns (answer, turn, core)."""
    awaiting = trip.awaiting if trip else None
    out = apply_guards(controller_plan(**said), message, has_reel=False, awaiting=awaiting)
    core = FakeCore({})
    answer, turn = run_turn(out, core, message=message, trip=trip, today=THURSDAY)
    return answer, turn, core


def test_today_question_answers_from_code():
    answer, _, core = ask("hôm nay là ngày mấy", intent="search")
    assert answer.text == "Hôm nay là thứ Năm, 26/11/2026."
    assert answer.kind == "answer" and answer.facts == [{"type": "date_info"}]
    assert core.calls == []


def test_weekend_question_names_both_days():
    answer, _, _ = ask("cuối tuần này là ngày mấy", intent="consult")
    assert answer.text == "Cuối tuần này là thứ Bảy 28/11 và Chủ nhật 29/11."


def test_tomorrow_question():
    answer, _, _ = ask("mai là thứ mấy", intent="clarify")
    assert answer.text == "Mai là thứ Sáu, 27/11."


def test_date_question_keeps_pending_plan_question():
    awaiting = Awaiting(intent="plan_trip", missing="dates", nights=1)
    trip = TripContext(place="Vũng Tàu", awaiting=awaiting)
    answer, turn, _ = ask("hôm nay là ngày mấy", trip, intent="plan_trip", place="Vũng Tàu")
    assert answer.text.endswith("Mình xếp tiếp chuyến Vũng Tàu cho bạn nha?")
    memory = turn.next_trip(answer)
    assert memory.awaiting == awaiting and memory.place == "Vũng Tàu"
    assert memory.date_from is None


def test_date_question_with_place_is_not_ask_date():
    out = apply_guards(
        controller_plan(intent="weather", place="Vũng Tàu", day_ref="tomorrow"),
        "thời tiết vũng tàu mai thứ mấy",
        has_reel=False,
    )
    assert out.intent == "weather"
