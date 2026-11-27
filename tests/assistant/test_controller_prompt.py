"""Controller prompt = core + modules picked by code; a missing module is re-asked once (TF31)."""

import asyncio
import json
from uuid import uuid4

import pytest

from app.clients.llm.base import LlmResult
from app.services.assistant import understand
from app.services.assistant.controller import EMPTY_OUTPUT, ControllerOutput
from app.services.assistant.controller_prompt import (
    MODULE_ORDER,
    PROMPT_DIR,
    build_system_prompt,
    needed_module,
    select_modules,
)
from app.services.assistant.schemas import Awaiting, ChatRequest, TripContext


def modules_of(message: str, trip: dict | None = None, **request) -> frozenset[str]:
    request_body = ChatRequest(
        conversation_id=uuid4(),
        message=message,
        trip=TripContext.model_validate(trip) if trip is not None else None,
        **request,
    )
    return select_modules(request_body, has_date_cue=False)


STAY_CARD = {"lastCards": [{"ref": "r1", "kind": "stay", "id": "s1"}]}
REEL_CARD = {"lastCards": [{"ref": "r1", "kind": "video", "id": "v1"}]}
STOP = {"id": "p1", "name": "Chợ Hàn", "lat": 16.0, "lng": 108.2}


@pytest.mark.parametrize(
    ("message", "trip", "expected"),
    [
        ("homestay đà lạt", None, {"stay_filters"}),
        ("xin chào bạn ơi", None, set()),
        ("từ 1tr đến 2tr một đêm", None, {"stay_filters"}),
        ("chuyển Chợ Hàn sang ngày 2", None, {"plan_edit"}),
        ("căn nào rẻ hơn", STAY_CARD, {"stay_filters"}),
        ("bỏ chợ Hàn đi", {"days": [[STOP]]}, {"plan_edit"}),
        ("cho mình xem", REEL_CARD, {"reel"}),
        (
            "lấy cái thứ 2",
            {"pending": [{"name": "A", "source": "tripflix", "id": "1"}]},
            {"booking_options"},
        ),
        ("chốt luôn đi nhé bạn ơi", None, {"booking_options"}),
        ("cuối tuần đi đâu chơi", None, {"consult"}),
        ("alo", {"prefs": {"vibe": ["quiet"]}}, {"consult"}),
    ],
)
def test_modules_follow_state(message, trip, expected):
    assert modules_of(message, trip) == expected


def test_reel_module_follows_the_open_post():
    assert modules_of("video này đi mấy ngày", None, context_post_id=uuid4()) == {"reel"}


def test_calendar_follows_the_date_cue():
    request = ChatRequest(conversation_id=uuid4(), message="alo")
    assert select_modules(request, has_date_cue=True) == {"calendar"}


def test_prompt_order_is_fixed():
    core = build_system_prompt(frozenset())
    reel = (PROMPT_DIR / "modules/reel.v1.md").read_text(encoding="utf-8").strip()
    calendar = (PROMPT_DIR / "modules/calendar.v1.md").read_text(encoding="utf-8").strip()
    both = build_system_prompt(frozenset({"reel", "calendar"}))
    assert both == "\n\n".join([core, calendar, reel])
    assert both == build_system_prompt(frozenset({"calendar", "reel"}))
    assert MODULE_ORDER.index("calendar") < MODULE_ORDER.index("reel")


def test_core_lists_every_intent():
    core = build_system_prompt(frozenset())
    intents = ControllerOutput.model_fields["intent"].annotation.__args__  # type: ignore[union-attr]
    assert [intent for intent in intents if f"- {intent}:" not in core] == []


def test_needed_module_by_intent_and_filter_slot():
    def out(**fields) -> ControllerOutput:
        return ControllerOutput.model_validate(EMPTY_OUTPUT | fields)

    assert needed_module(out(intent="post_itinerary")) == "reel"
    assert needed_module(out(intent="find_stay")) is None
    assert needed_module(out(intent="find_stay", min_stars=4)) == "stay_filters"
    assert needed_module(out(intent="search")) is None


class ScriptedController:
    def __init__(self, *intents: str):
        self.intents = list(intents)
        self.systems: list[str] = []

    async def agenerate(self, system, user, schema):
        self.systems.append(system)
        output = json.dumps(EMPTY_OUTPUT | {"intent": self.intents.pop(0)})
        return LlmResult(
            output=output, model_name="fake", input_tokens=100, output_tokens=20,
            cost_usd=0.5, finish_reason="stop", latency_ms=10,
        )  # fmt: skip


def run(monkeypatch, message, llm, trip=None):
    monkeypatch.setattr(understand, "get_role_llm", lambda role: llm)
    request = ChatRequest(conversation_id=uuid4(), message=message, trip=trip)
    usage: list[LlmResult] = []
    parsed, result = asyncio.run(understand.understand(request, max_turns=6, on_usage=usage.append))
    return parsed, result, usage


def test_recall_adds_missing_module(monkeypatch):
    llm = ScriptedController("post_itinerary", "post_itinerary")
    _, result, usage = run(monkeypatch, "ngày thứ hai có gì", llm)
    reel = (PROMPT_DIR / "modules/reel.v1.md").read_text(encoding="utf-8").strip()
    assert len(llm.systems) == 2
    assert reel not in llm.systems[0] and reel in llm.systems[1]
    # The re-call keeps what the first call had ("ngày thứ hai" is a date cue) plus the module.
    assert llm.systems[1] == build_system_prompt(frozenset({"calendar", "reel"}))
    # Both calls are billed: each reaches on_usage, and the returned result is their sum.
    assert len(usage) == 2
    assert (result.input_tokens, result.output_tokens, result.cost_usd) == (200, 40, 1.0)


def test_no_recall_when_module_loaded(monkeypatch):
    llm = ScriptedController("post_itinerary")
    trip = TripContext.model_validate(REEL_CARD)
    _, result, usage = run(monkeypatch, "ngày thứ hai có gì", llm, trip)
    assert len(llm.systems) == 1 and len(usage) == 1 and result.input_tokens == 100


def test_recall_for_filter_slots(monkeypatch):
    # "lọc 4 sao dưới 1 triệu" with no stay cue: the model says find_stay with filters.
    llm = ScriptedController("find_stay", "find_stay")
    llm_out = json.dumps(EMPTY_OUTPUT | {"intent": "find_stay", "min_stars": 4})

    async def agenerate(system, user, schema):
        llm.systems.append(system)
        return LlmResult(
            output=llm_out, model_name="fake", input_tokens=100, output_tokens=20,
            finish_reason="stop",
        )  # fmt: skip

    llm.agenerate = agenerate  # type: ignore[method-assign]
    trip = TripContext(place="Đà Lạt", awaiting=Awaiting(intent="find_stay", missing="dates"))
    run(monkeypatch, "lọc 4 sao dưới 1 triệu", llm, trip)
    stay_filters = (PROMPT_DIR / "modules/stay_filters.v1.md").read_text(encoding="utf-8").strip()
    assert len(llm.systems) == 2 and stay_filters in llm.systems[1]
