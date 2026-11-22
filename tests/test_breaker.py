import asyncio
from collections.abc import Sequence
from dataclasses import replace
from typing import Any
from unittest.mock import AsyncMock, Mock

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
