"""LlmClient that wraps another one with a circuit breaker (decorator: same port, no caller
change). When the provider keeps failing, calls fail at once with LlmUnavailableError so the
worker can put the post back for later instead of waiting ~96 s of timeouts per post.

The chat path (agenerate) treats a 429 that only throttles us as a wait, not a failure: it
waits Retry-After once when that is short, and never counts it towards the breaker. In the
load test of 26/11 the provider's 429 at ~7 turns/s opened the breaker and every user lost
the LLM. Out of credit is a 429 too at OpenAI ("insufficient_quota"): that one is an outage.
"""

import asyncio
import dataclasses
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.clients.llm.base import LlmClient, LlmResult
from app.core.breaker import CircuitBreaker


class LlmUnavailableError(Exception):
    def __init__(self, retry_in_seconds: float) -> None:
        super().__init__(f"LLM breaker open, retry in {retry_in_seconds:.0f} s")
        self.retry_in_seconds = retry_in_seconds


RATE_LIMIT_MAX_WAIT_SECONDS = 2.0  # [HIỆU CHỈNH] a chat turn has 12 s in all
RATE_LIMIT_DEFAULT_WAIT_SECONDS = 1.0  # [HIỆU CHỈNH] when the 429 says nothing


def rate_limit_wait(error: BaseException) -> float | None:
    """Seconds the provider asks us to wait when it throttles us; None for any other error."""
    if not isinstance(error, httpx.HTTPStatusError):
        return None
    response = error.response
    if response.status_code != httpx.codes.TOO_MANY_REQUESTS:
        return None
    try:
        body = response.json()
    except ValueError:
        body = None
    detail = body.get("error") if isinstance(body, dict) else None
    codes = {detail.get("code"), detail.get("type")} if isinstance(detail, dict) else set()
    if "insufficient_quota" in codes:
        return None
    for header, scale in (("retry-after-ms", 1000.0), ("retry-after", 1.0)):
        try:
            return float(response.headers[header]) / scale
        except (KeyError, ValueError):
            continue
    return RATE_LIMIT_DEFAULT_WAIT_SECONDS


class GuardedLlmClient:
    def __init__(
        self,
        inner: LlmClient,
        breaker: CircuitBreaker,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.inner = inner
        self.breaker = breaker
        self.model = inner.model
        self.sleep = sleep

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult:
        if self.breaker.is_open():
            raise LlmUnavailableError(self.breaker.seconds_left())
        try:
            result = self.inner.generate(system, user, schema)
        except Exception:
            self.breaker.record_failure()
            raise
        self.breaker.record_success()
        return result

    async def agenerate(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult:
        """Async twin for the chat route; an adapter without one runs in a worker thread."""
        if self.breaker.is_open():
            raise LlmUnavailableError(self.breaker.seconds_left())
        # CancelledError is not an Exception: the client left, not a provider failure.
        start = time.perf_counter()
        try:
            result = await self._call(system, user, schema)
        except Exception as error:
            wait = rate_limit_wait(error)
            if wait is None:
                self.breaker.record_failure()
                raise
            if wait > RATE_LIMIT_MAX_WAIT_SECONDS:
                raise  # throttled, not down: the breaker stays shut
            await self.sleep(wait)
            try:
                result = await self._call(system, user, schema)
            except Exception as again:
                if rate_limit_wait(again) is None:
                    self.breaker.record_failure()
                raise
        end = time.perf_counter()
        self.breaker.record_success()
        return dataclasses.replace(result, latency_ms=round((end - start) * 1000))

    async def _call(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult:
        native = getattr(self.inner, "agenerate", None)
        if native is not None:
            return await native(system, user, schema)
        return await asyncio.to_thread(self.inner.generate, system, user, schema)
