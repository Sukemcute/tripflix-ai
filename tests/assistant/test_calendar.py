"""Real-time calendar, Vietnamese holidays and today's flights (TF31, design 2026-11-26)."""

import asyncio
import json
from datetime import date, datetime
from uuid import uuid4

from app.services.assistant import calendar
from app.services.assistant.admission import VIETNAM
from app.services.assistant.controller import apply_guards, to_understanding
from app.services.assistant.schemas import Awaiting, ChatRequest, TripContext
from app.services.assistant.turn import Turn
from app.services.assistant.understand import build_understanding_input
from evals.assistant.run import controller_plan
from tests.assistant.test_dates import THURSDAY, ask
from tests.assistant.test_report_regressions import FakeCore, FakeWeather

NOW = datetime(2026, 11, 26, 8, 15, tzinfo=VIETNAM)  # Thursday


def test_calendar_days_and_weekends():
    built = calendar.build_calendar(NOW)
    assert (built["now"], built["today"], built["weekday"]) == (
        "2026-11-26 08:15",
        "2026-11-26",
        "thứ Năm",
    )
    assert built["days"][0] == {"date": "2026-11-26", "label": "T5 26/11", "rel": "hôm nay"}
    assert built["days"][1] == {"date": "2026-11-27", "label": "T6 27/11", "rel": "mai"}
    assert built["days"][2]["rel"] == "mốt" and "rel" not in built["days"][3]
    assert len(built["days"]) == 14
    assert built["thisWeekend"] == ["2026-11-28", "2026-11-29"]
    assert built["nextWeekend"] == ["2026-12-05", "2026-12-06"]
    assert built["nextWeek"] == ["2026-11-30", "2026-12-06"]


def test_calendar_on_sunday():
    sunday = datetime(2026, 11, 29, 9, 0, tzinfo=VIETNAM)
    built = calendar.build_calendar(sunday)
    assert built["thisWeekend"] == ["2026-11-29"]
    assert built["nextWeek"] == ["2026-11-30", "2026-12-06"]


def test_holidays_loaded_and_in_window():
    holidays = {h["name"]: h for h in calendar.build_calendar(NOW)["holidays"]}
    assert holidays["Tết Nguyên Đán"] == {
        "name": "Tết Nguyên Đán",
        "from": "2027-02-05",
        "to": "2027-02-09",
        "isLunar": True,
    }
    assert holidays["Lễ 30/4 – 1/5"]["from"] == "2027-04-30"
    assert holidays["Giỗ Tổ Hùng Vương"]["from"] == "2027-04-16"
    assert holidays["Quốc khánh"]["from"] == "2027-09-01"
    # Tết Dương lịch 1/1/2027 is inside the 400 days, the past 2026 holidays are not.
    assert holidays["Tết Dương lịch"]["from"] == "2027-01-01"
    assert all(h["to"] >= "2026-11-26" for h in holidays.values())


def test_controller_input_has_calendar():
    request = ChatRequest(conversation_id=uuid4(), message="thứ 6 tuần sau đi vũng tàu")
    sent = json.loads(build_understanding_input(request, now=NOW))
    assert sent["calendar"]["days"][1]["label"] == "T6 27/11"
    assert list(sent)[-1] == "message"


def calendar_sent(message: str, trip: TripContext | None = None) -> bool:
    request = ChatRequest(conversation_id=uuid4(), message=message, trip=trip)
    return "calendar" in json.loads(build_understanding_input(request, now=NOW))


def test_input_has_calendar_only_with_date_cue():
    assert calendar_sent("homestay đà lạt cuối tuần sau")
    assert calendar_sent("21/11")
    assert calendar_sent("đi Đà Lạt dịp Tết 2 đêm")
    for phrase in ("tuần tới đi Đà Lạt", "cuối tháng này đi Đà Lạt", "tháng sau đi Huế"):
        assert calendar_sent(phrase)
    assert calendar_sent("đi Sapa sang năm")
    assert calendar_sent("ngày 20 đi Đà Lạt")
    assert not calendar_sent("homestay đà lạt")
    assert not calendar_sent("hi, tìm khách sạn Đà Lạt")
    # A short reply to "đi ngày nào?" carries the date words only when the calendar is sent.
    asked_dates = Awaiting(intent="find_stay", missing="dates")
    assert calendar_sent("Vũng tàu", TripContext(awaiting=asked_dates))
    assert not calendar_sent("Vũng tàu", TripContext(awaiting=Awaiting(intent="plan_trip")))
    # Dates already set: only a message that moves them needs the calendar.
    dated = TripContext(place="Đà Lạt", date_from=date(2026, 12, 5))
    assert calendar_sent("lùi lại một tuần", dated)
    assert calendar_sent("đổi lịch giúp mình", dated)
    for phrase in ("hoãn 1 tuần", "dời lại 2 hôm", "đẩy lên 2 ngày", "dời sang thứ 7"):
        assert calendar_sent(phrase, dated)
    assert not calendar_sent("tìm khách sạn rẻ hơn", dated)


def test_date_question_about_tet():
    answer, _, core = ask("Tết năm nay ngày mấy", intent="search")
    assert answer.kind == "answer" and core.calls == []
    assert answer.text.startswith("Mùng 1 Tết Nguyên Đán 2027 vào thứ Bảy, 06/02/2027.")
    assert "05/02" in answer.text and "09/02" in answer.text
    answer, _, _ = ask("30/4 năm sau là thứ mấy", intent="search")
    assert answer.text.startswith("Lễ 30/4 – 1/5 2027 vào thứ Sáu, 30/04/2027.")


def test_holiday_with_a_place_is_not_a_date_question():
    out = apply_guards(
        controller_plan(intent="weather", place="Đà Lạt"),
        "tết đà lạt thời tiết thế nào",
        has_reel=False,
    )
    assert out.intent == "weather"


def test_verifier_grounds_dates_found_in_the_calendar():
    from app.services.assistant.verifier import verify

    built = calendar.build_calendar(NOW)
    sentence = ["Cuối tuần này là 28/11 và 29/11 nha, còn Tết là 06/02/2027."]
    kept, _ = verify(sentence, [], set(), "cuối tuần", today=NOW.date(), calendar=built)
    assert kept == sentence
    kept, dropped = verify(sentence, [], set(), "cuối tuần", today=NOW.date())
    assert not kept and dropped["V2_ungrounded_number"] == 1
    kept, _ = verify(["Cuối tuần này là 20/12 nha."], [], set(), "cuối tuần", calendar=built)
    assert not kept  # 20/12 is not a day of the calendar given


def test_relative_days_come_from_the_calendar_when_the_model_skips_them():
    thursday = THURSDAY
    cases = {
        "3 ngày nữa mình bay ra hà nội": (date(2026, 11, 29), None),
        "thứ 6 tuần sau đi vũng tàu": (date(2026, 12, 4), None),
        "t2 tuần sau tìm phòng": (date(2026, 11, 30), None),
        "đầu tuần sau đi đà lạt": (date(2026, 11, 30), None),
        "nghỉ Tết đi Đà Lạt": (date(2027, 2, 5), date(2027, 2, 9)),
        "dịp 30/4 năm sau đi đâu": (date(2027, 4, 30), date(2027, 5, 1)),
        "dịp giỗ tổ đi huế": (date(2027, 4, 16), None),
    }
    for message, want in cases.items():
        assert calendar.relative_dates(message, thursday) == want, message
    assert calendar.relative_dates("ks đà lạt 1/5", thursday) is None


def test_guard_fills_start_and_end_from_the_calendar():
    said = controller_plan(intent="search", place="Đà Lạt", day_ref="next_weekend", query="x")
    out = apply_guards(said, "thứ 6 tuần sau đi đà lạt", has_reel=False, today=THURSDAY)
    parsed = to_understanding(out, None, THURSDAY)
    assert (parsed.check_in, parsed.day_ref) == (date(2026, 12, 4), "none")
    out = apply_guards(said, "nghỉ Tết đi đà lạt", has_reel=False, today=THURSDAY)
    parsed = to_understanding(out, None, THURSDAY)
    assert (parsed.check_in, parsed.check_out) == (date(2027, 2, 5), date(2027, 2, 9))


def test_guard_drops_dates_the_message_never_said():
    # "3 ngày 2 đêm" is a length: a weekend or calendar date would build the plan at once.
    said = controller_plan(
        intent="plan_trip",
        place="Vũng Tàu",
        day_ref="this_weekend",
        start={"day": 21, "month": 11},
        end={"day": 23, "month": 11},
    )
    message = "Lên lịch trình Vũng Tàu 3 ngày 2 đêm, xuất phát từ TP.HCM"
    out = apply_guards(said, message, has_reel=False, today=THURSDAY)
    assert (out.day_ref, out.start, out.end) == ("none", None, None)
    kept = apply_guards(said, "xếp Vũng Tàu cuối tuần 21/11", has_reel=False, today=THURSDAY)
    assert (kept.day_ref, kept.start) == ("this_weekend", said.start)


def test_nights_alone_do_not_send_the_calendar():
    assert not calendar_sent("Lên lịch trình Vũng Tàu 3 ngày 2 đêm")
    assert calendar_sent("Lên lịch trình Vũng Tàu 3 ngày 2 đêm cuối tuần này")


def test_turn_today_follows_now():
    request = ChatRequest(conversation_id=uuid4(), message="x")

    async def go():
        async with FakeCore({}).client() as client:
            return Turn(request, None, core=client, weather=FakeWeather([]), now=NOW).today

    assert asyncio.run(go()) == date(2026, 11, 26)


def test_guard_unaccented_flight_change_in_a_plan_is_change_transport():
    said = controller_plan(intent="move_stop", place="Đà Nẵng")
    out = apply_guards(said, "Doi chuyen bay", has_reel=False, in_plan=True, today=THURSDAY)
    assert out.intent == "change_transport"
    out = apply_guards(said, "Doi chuyen bay", has_reel=False, in_plan=False, today=THURSDAY)
    assert out.intent == "move_stop"
