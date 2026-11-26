"""Relative days and date questions, on a fixed Thursday (live test 2026-11-26)."""

import json
from datetime import date

import pytest

from app.services.assistant import planner
from app.services.assistant.controller import DayMonth, apply_guards, to_understanding
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


def test_start_day_day_after_tomorrow():
    out = controller_plan(intent="weather", place="Vũng Tàu", day_ref="day_after_tomorrow")
    assert planner.start_day(to_understanding(out, None, THURSDAY), THURSDAY) == date(2026, 11, 28)


@pytest.mark.parametrize(
    ("day_ref", "want"),
    [
        ("monday", date(2026, 11, 30)),
        ("tuesday", date(2026, 12, 1)),
        ("wednesday", date(2026, 12, 2)),
        ("thursday", date(2026, 11, 26)),
        ("friday", date(2026, 11, 27)),
    ],
)
def test_start_day_weekdays(day_ref, want):
    out = controller_plan(intent="find_stay", place="Vũng Tàu", day_ref=day_ref)
    assert planner.start_day(to_understanding(out, None, THURSDAY), THURSDAY) == want


@pytest.mark.parametrize(
    ("message", "day_ref"),
    [
        ("mốt đi được không", "day_after_tomorrow"),
        ("ngày kia ở vũng tàu có mưa không", "day_after_tomorrow"),
        ("tìm phòng vũng tàu thứ 6 tuần này", "friday"),
        ("ks vũng tàu t2", "monday"),
    ],
)
def test_day_cue_keeps_mot(message, day_ref):
    out = apply_guards(controller_plan(intent="weather", day_ref=day_ref), message, has_reel=False)
    assert out.day_ref == day_ref


def test_day_cue_drops_mot_when_message_says_one_night():
    out = apply_guards(
        controller_plan(intent="find_stay", place="Vũng Tàu", day_ref="day_after_tomorrow"),
        "tìm phòng vũng tàu một đêm",
        has_reel=False,
    )
    assert out.day_ref == "none"


def test_day_after_tomorrow_question():
    answer, _, _ = ask("ngày mốt là ngày mấy", intent="clarify")
    assert answer.text == "Ngày mốt là thứ Bảy, 28/11."


def test_weekend_plan_dates():
    # Observed from the live Controller: day_ref this_weekend plus start/end = today and today + 2.
    message = "xếp lịch trình vũng tàu cuối tuần này 2 ngày 1 đêm"
    said = controller_plan(
        intent="plan_trip",
        place="Vũng Tàu",
        query="vũng tàu",
        day_ref="this_weekend",
        start=DayMonth(day=26, month=11),
        end=DayMonth(day=28, month=11),
        nights=1,
    )
    out = apply_guards(said, message, has_reel=False)
    parsed = to_understanding(out, None, THURSDAY, message=message)
    assert planner.stay_range(parsed, THURSDAY) == (date(2026, 11, 28), date(2026, 11, 29))


def test_typed_dates_still_beat_the_relative_day():
    said = controller_plan(
        intent="find_stay",
        place="Vũng Tàu",
        day_ref="saturday",
        start=DayMonth(day=21, month=12),
        end=DayMonth(day=22, month=12),
    )
    out = apply_guards(said, "ks vũng tàu t7 21/12 đến 22/12", has_reel=False)
    parsed = to_understanding(out, None, THURSDAY)
    assert planner.stay_range(parsed, THURSDAY) == (date(2026, 12, 21), date(2026, 12, 22))


@pytest.mark.parametrize(
    ("message", "query", "sent"),
    [
        ("chơi gì vậy", "chơi gì", "Vũng Tàu chơi gì"),
        ("đà lạt thì sao", "đà lạt", "đà lạt"),
        ("ăn gì ở vũng tàu", "ăn gì ở vũng tàu", "ăn gì ở vũng tàu"),
    ],
)
def test_follow_up_search_keeps_trip_place(message, query, sent):
    core = FakeCore({"/api/search": {"sections": []}})
    out = controller_plan(intent="search", query=query)
    run_turn(out, core, message=message, trip=TripContext(place="Vũng Tàu"), today=THURSDAY)
    (body,) = [json.loads(raw) for path, raw in core.bodies if path == "/api/search"]
    assert body == {"q": sent}


@pytest.mark.parametrize("said_ref", ["this_weekend", "none", "saturday"])
def test_one_spoken_weekday_beats_a_wrong_day_ref_or_remembered_dates(said_ref):
    said = controller_plan(
        intent="find_stay",
        place="Vũng Tàu",
        day_ref=said_ref,
        start=DayMonth(day=28, month=11),
        end=DayMonth(day=29, month=11),
    )
    out = apply_guards(said, "tìm phòng vũng tàu thứ 6 tuần này", has_reel=False, today=THURSDAY)
    parsed = to_understanding(out, None, THURSDAY)
    assert parsed.day_ref == "friday"
    assert planner.start_day(parsed, THURSDAY) == date(2026, 11, 27)


def test_mot_beats_remembered_dates():
    trip = TripContext(place="Vũng Tàu", date_from=date(2026, 11, 27))
    said = controller_plan(intent="find_stay", place="Vũng Tàu", day_ref="tomorrow")
    out = apply_guards(said, "mốt đi được không", has_reel=False, today=THURSDAY)
    parsed = to_understanding(out, trip, THURSDAY)
    assert parsed.day_ref == "day_after_tomorrow"
    assert planner.start_day(parsed, THURSDAY) == date(2026, 11, 28)
    # the day the user just said replaces the remembered ones in the trip memory too
    answer, turn, _ = ask("mốt đi được không", trip, intent="find_stay", place="Vũng Tàu")
    assert turn.next_trip(answer).date_from == date(2026, 11, 28)


@pytest.mark.parametrize("said", ["plan_trip", "search", "find_stay", "clarify"])
def test_can_i_go_day_is_weather(said):
    out = apply_guards(
        controller_plan(intent=said, place="", day_ref="day_after_tomorrow"),
        "mốt đi được không",
        has_reel=False,
        today=THURSDAY,
        trip_place="Vũng Tàu",
    )
    assert out.intent == "weather"
    assert (
        apply_guards(
            controller_plan(intent="find_stay", place="Vũng Tàu", day_ref="tomorrow"),
            "tìm khách sạn vũng tàu mai đi được không",
            has_reel=False,
            today=THURSDAY,
        ).intent
        == "find_stay"
    )
