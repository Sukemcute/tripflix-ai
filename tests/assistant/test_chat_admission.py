"""Who may start a chat turn: locks, per-minute and daily budgets, guests (TF31 v3)."""

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError

from app.api import chat as chat_api
from app.api.chat import get_chat_settings, get_gate
from app.clients.llm.base import LlmResult
from app.core.config import ChatSettings
from app.main import app
from app.services.assistant import Understanding
from app.services.assistant.admission import (
    ChatRejectedError,
    TurnGate,
    guest_identity,
    user_identity,
)

NOON = datetime(2026, 11, 16, 5, 0, tzinfo=UTC)  # 12:00 in Vietnam


def make_gate(shared=None, **overrides) -> TurnGate:
    return TurnGate(ChatSettings.model_construct(**overrides), shared, now=lambda: NOON)


def run(coro):
    return asyncio.run(coro)


def test_second_turn_of_the_same_identity_waits():
    gate = make_gate()
    user = user_identity("u1")

    async def scenario():
        first = await gate.enter(user)
        with pytest.raises(ChatRejectedError) as busy:
            await gate.enter(user)
        await gate.leave(first)
        await gate.leave(await gate.enter(user))  # free again after the first left
        return busy.value

    error = run(scenario())
    assert (error.status, error.code) == (409, "TURN_IN_PROGRESS")


def test_full_process_rejects_at_once_without_queueing():
    gate = make_gate(chat_max_inflight=2)

    async def scenario():
        await gate.enter(user_identity("a"))
        await gate.enter(user_identity("b"))
        with pytest.raises(ChatRejectedError) as busy:
            await gate.enter(user_identity("c"))
        # The rejected turn must not keep its lock.
        assert await gate.local.acquire("chat:busy:user:c", "probe", 1000)
        return busy.value

    error = run(scenario())
    assert (error.status, error.code, error.retry_after) == (503, "CHAT_BUSY", 3)


def test_guest_over_daily_budget_must_log_in():
    gate = make_gate(chat_guest_daily_turns=2)
    guest = guest_identity("10.0.0.1", "salt")

    async def scenario():
        for _ in range(2):
            ticket = await gate.enter(guest)
            await gate.settle(ticket, tokens=100, cost_usd=0.0001)
            await gate.leave(ticket)
        with pytest.raises(ChatRejectedError) as limited:
            await gate.enter(guest)
        return limited.value

    error = run(scenario())
    assert (error.status, error.code, error.is_login_required) == (429, "GUEST_LIMIT_REACHED", True)
    assert error.retry_after == 12 * 3600  # until midnight in Vietnam


def test_guest_token_budget_counts_real_usage():
    gate = make_gate(chat_guest_daily_tokens=1000)
    guest = guest_identity("10.0.0.2", "salt")

    async def scenario():
        ticket = await gate.enter(guest)
        await gate.settle(ticket, tokens=1000, cost_usd=0.001)
        await gate.leave(ticket)
        with pytest.raises(ChatRejectedError):
            await gate.enter(guest)

    run(scenario())


def test_member_over_budget_is_degraded_not_blocked():
    gate = make_gate(chat_user_daily_turns=1)
    user = user_identity("u2")

    async def scenario():
        ticket = await gate.enter(user)
        await gate.settle(ticket, tokens=10, cost_usd=0.0)
        await gate.leave(ticket)
        return await gate.enter(user)

    assert run(scenario()).degraded == ["quota"]


def test_system_cap_degrades_everyone():
    gate = make_gate(chat_system_daily_usd=0.01)

    async def scenario():
        ticket = await gate.enter(user_identity("big"))
        await gate.settle(ticket, tokens=10, cost_usd=0.02)
        await gate.leave(ticket)
        return await gate.enter(user_identity("someone-else"))

    assert run(scenario()).degraded == ["quota"]


def test_per_minute_limit():
    gate = make_gate(chat_user_turns_per_minute=2)
    user = user_identity("u3")

    async def scenario():
        for _ in range(2):
            await gate.leave(await gate.enter(user))
        with pytest.raises(ChatRejectedError) as limited:
            await gate.enter(user)
        return limited.value

    assert run(scenario()).code == "RATE_LIMITED"


class DownStore:
    """A shared store that is unreachable for every call."""

    def __getattr__(self, name):
        async def fail(*args):
            raise RedisConnectionError("down")

        return fail


def test_store_outage_keeps_the_lock_and_lets_turns_through():
    gate = make_gate(DownStore(), chat_guest_daily_turns=1)
    guest = guest_identity("10.0.0.3", "salt")

    async def scenario():
        first = await gate.enter(guest)
        with pytest.raises(ChatRejectedError):
            await gate.enter(guest)  # the lock falls back to process memory
        await gate.settle(first, tokens=10, cost_usd=0.0)
        await gate.leave(first)
        await gate.leave(await gate.enter(guest))  # daily budget not enforced while down

    run(scenario())


def test_guest_ip_is_never_kept_in_clear():
    assert "10.0.0.9" not in guest_identity("10.0.0.9", "salt").key
    assert guest_identity("10.0.0.9", "a") != guest_identity("10.0.0.9", "b")


@pytest.fixture
def chat_client(monkeypatch):
    seen: dict[str, int] = {}

    async def classify(request, *, max_turns, on_usage):
        seen["turns"] = max_turns
        result = LlmResult(output="", model_name="test", input_tokens=300, output_tokens=50)
        on_usage(result)
        return Understanding(intent="small_talk"), result

    monkeypatch.setattr(chat_api, "understand", classify)
    monkeypatch.setattr(chat_api, "publish_usage", AsyncMock())
    settings = ChatSettings.model_construct(
        chat_llm_enabled=True,
        chat_guest_daily_turns=1,
        # Defaults are wide for everyone while testing (2026-11-17): set the two apart here.
        chat_guest_history_turns=4,
        chat_user_history_turns=6,
        # Small talk now has facts for the Responder: keep this test off the network.
        chat_responder_enabled=False,
    )
    gate = TurnGate(settings, None)
    app.dependency_overrides[get_chat_settings] = lambda: settings
    app.dependency_overrides[get_gate] = lambda: gate
    with TestClient(app) as client:
        yield client, gate, seen
    app.dependency_overrides.clear()


def test_guest_chats_then_is_asked_to_log_in(chat_client):
    client, gate, seen = chat_client
    body = {"conversationId": str(uuid4()), "message": "Bạn là ai?"}
    first = client.post("/chat", json=body)
    assert first.status_code == 200
    assert seen["turns"] == 4  # guests send a shorter history to the LLM
    done = json.loads(first.text.strip().split("\n\n")[-1].split("data: ")[1])
    assert done["usage"]["inputTokens"] == 300
    assert gate.inflight == 0  # released after the stream

    second = client.post("/chat", json=body)
    assert second.status_code == 429
    assert second.headers["retry-after"]
    assert second.json() | {"retryAfterSeconds": 0} == {
        "code": "GUEST_LIMIT_REACHED",
        "message": second.json()["message"],
        "retryAfterSeconds": 0,
        "loginRequired": True,
    }
