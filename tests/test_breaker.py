import asyncio
from collections.abc import Sequence
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from app.clients.llm import guarded
from app.clients.llm.base import LlmResult
from app.clients.llm.guarded import GuardedLlmClient, LlmUnavailableError
from app.core.breaker import CircuitBreaker
from app.services.summary.comment_classifier import (
    ClassifierUnavailableError,
    CommentLabels,
    GuardedClassifier,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_opens_after_failures_in_a_row_and_lets_one_call_through_later() -> None:
    clock = Clock()
    breaker = CircuitBreaker("x", threshold=2, open_seconds=60, clock=clock)

    breaker.record_failure()
    assert not breaker.is_open()
    breaker.record_failure()
    assert breaker.is_open() and breaker.seconds_left() == 60

    clock.now = 60  # half-open: one call goes through
    assert not breaker.is_open()
    breaker.record_failure()  # still sick: open again at once
    assert breaker.is_open()

    clock.now = 120
    breaker.record_success()
    assert not breaker.is_open() and breaker.failures == 0


def test_a_success_resets_the_count() -> None:
    breaker = CircuitBreaker("x", threshold=2, clock=Clock())
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()

    assert not breaker.is_open()


class FlakyLlm:
    model = "m1"

    def __init__(self) -> None:
        self.calls = 0
        self.is_down = True

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult:
        self.calls += 1
        if self.is_down:
            raise TimeoutError("provider slow")
        return LlmResult(output="{}", model_name="m1", input_tokens=1, output_tokens=1)


def test_an_open_llm_breaker_fails_at_once_without_calling_the_provider() -> None:
    inner = FlakyLlm()
    llm = GuardedLlmClient(inner, CircuitBreaker("llm", threshold=2, clock=Clock()))

    for _ in range(2):
        with pytest.raises(TimeoutError):
            llm.generate("s", "u", {})
    with pytest.raises(LlmUnavailableError):
        llm.generate("s", "u", {})

    assert inner.calls == 2 and llm.model == "m1"


@pytest.mark.parametrize("native", [False, True])
def test_async_llm_measures_provider_latency_without_changing_result(monkeypatch, native):
    original = LlmResult("{}", "m1", 7, 11, cost_usd=0.01, finish_reason="stop")
    counter = Mock(side_effect=[100.0, 100.123])
    monkeypatch.setattr(guarded.time, "perf_counter", counter)

    def generate(*args):
        assert args == ("s", "u", {}) and counter.call_count == 1
        return original

    inner = Mock(spec=FlakyLlm)
    inner.generate = Mock(side_effect=generate)
    if native:
        inner.agenerate = AsyncMock(side_effect=generate)
    llm = GuardedLlmClient(inner, CircuitBreaker("llm", clock=Clock()))
    result = asyncio.run(llm.agenerate("s", "u", {}))
    assert result == replace(original, latency_ms=123)
    assert isinstance(result.latency_ms, int) and result.latency_ms >= 0
    assert original.latency_ms is None and counter.call_count == 2
    if native:
        inner.generate.assert_not_called()


@pytest.mark.parametrize("error", [TimeoutError, asyncio.CancelledError])
def test_async_failure_and_cancellation_keep_breaker_behavior(error):
    inner = Mock(spec=FlakyLlm)
    inner.agenerate = AsyncMock(side_effect=error)
    breaker = CircuitBreaker("llm", clock=Clock())
    with pytest.raises(error):
        asyncio.run(GuardedLlmClient(inner, breaker).agenerate("s", "u", {}))
    assert breaker.failures == (0 if error is asyncio.CancelledError else 1)


def test_async_open_breaker_never_starts_latency_timer(monkeypatch):
    counter = Mock()
    monkeypatch.setattr(guarded.time, "perf_counter", counter)
    inner = Mock(spec=FlakyLlm)
    breaker = CircuitBreaker("llm", threshold=1, clock=Clock())
    breaker.record_failure()
    with pytest.raises(LlmUnavailableError):
        asyncio.run(GuardedLlmClient(inner, breaker).agenerate("s", "u", {}))
    counter.assert_not_called()
    inner.generate.assert_not_called()


class BrokenClassifier:
    version = "v-test"

    def classify(self, pairs: Sequence[tuple[str, str]]) -> list[CommentLabels]:
        raise RuntimeError("onnxruntime failed")


def test_a_failing_classifier_is_skipped_once_its_breaker_opens() -> None:
    classifier = GuardedClassifier(BrokenClassifier(), CircuitBreaker("c", threshold=1))

    with pytest.raises(RuntimeError):
        classifier.classify([("a", "")])
    with pytest.raises(ClassifierUnavailableError):
        classifier.classify([("a", "")])
    assert classifier.version == "v-test"


def test_a_late_success_does_not_close_an_open_breaker() -> None:
    # Load test 26/11: calls sent before the breaker opened came back fine and closed it at
    # once (34 opens in a minute), so "open 300 s" held a few seconds.
    clock = Clock()
    breaker = CircuitBreaker("x", threshold=2, open_seconds=60, clock=clock)
    breaker.record_failure()
    breaker.record_failure()

    breaker.record_success()
    assert breaker.is_open() and breaker.seconds_left() == 60

    clock.now = 60
    breaker.record_success()  # sent after the wait: the provider is back
    assert not breaker.is_open() and breaker.failures == 0


def throttled(headers: dict[str, str] | None = None, body: Any = None) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://llm.test/chat/completions")
    payload = body if body is not None else {"error": {"code": "rate_limit_exceeded"}}
    response = httpx.Response(429, headers=headers or {}, json=payload, request=request)
    return httpx.HTTPStatusError("429", request=request, response=response)


def guarded_async(*outcomes: Any) -> tuple[GuardedLlmClient, Mock, AsyncMock, CircuitBreaker]:
    inner = Mock(spec=FlakyLlm)
    inner.agenerate = AsyncMock(side_effect=list(outcomes))
    sleep = AsyncMock()
    breaker = CircuitBreaker("llm", threshold=3, clock=Clock())
    return GuardedLlmClient(inner, breaker, sleep=sleep), inner, sleep, breaker


OK = LlmResult("{}", "m1", 1, 1)


def test_async_rate_limit_waits_retry_after_and_tries_once_more() -> None:
    llm, inner, sleep, breaker = guarded_async(throttled({"retry-after-ms": "250"}), OK)

    assert asyncio.run(llm.agenerate("s", "u", {})).output == "{}"
    sleep.assert_awaited_once_with(0.25)
    assert inner.agenerate.await_count == 2 and breaker.failures == 0


def test_async_rate_limit_without_header_waits_the_default() -> None:
    llm, _, sleep, _ = guarded_async(throttled(), OK)
    asyncio.run(llm.agenerate("s", "u", {}))
    sleep.assert_awaited_once_with(guarded.RATE_LIMIT_DEFAULT_WAIT_SECONDS)


def test_async_rate_limit_is_not_a_breaker_failure() -> None:
    # Load test 26/11: 88 throttled turns opened the breaker and every user lost the LLM.
    llm, inner, _, breaker = guarded_async(*[throttled({"retry-after": "1"})] * 8)
    for _ in range(4):
        with pytest.raises(httpx.HTTPStatusError):
            asyncio.run(llm.agenerate("s", "u", {}))
    assert inner.agenerate.await_count == 8  # one more try each, never a third
    assert breaker.failures == 0 and not breaker.is_open()


def test_async_long_retry_after_gives_up_at_once() -> None:
    llm, inner, sleep, breaker = guarded_async(throttled({"retry-after": "30"}))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(llm.agenerate("s", "u", {}))
    sleep.assert_not_awaited()
    assert inner.agenerate.await_count == 1 and breaker.failures == 0


def test_async_out_of_credit_is_a_failure_not_a_wait() -> None:
    out_of_credit = throttled(body={"error": {"code": "insufficient_quota"}})
    llm, _, sleep, breaker = guarded_async(out_of_credit)
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(llm.agenerate("s", "u", {}))
    sleep.assert_not_awaited()
    assert breaker.failures == 1


def test_async_failure_after_a_rate_limit_counts_once() -> None:
    llm, _, _, breaker = guarded_async(throttled(), TimeoutError("slow"))
    with pytest.raises(TimeoutError):
        asyncio.run(llm.agenerate("s", "u", {}))
    assert breaker.failures == 1
