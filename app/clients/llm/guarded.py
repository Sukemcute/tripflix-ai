"""LlmClient that wraps another one with a circuit breaker (decorator: same port, no caller
change). When the provider keeps failing, calls fail at once with LlmUnavailableError so the
worker can put the post back for later instead of waiting ~96 s of timeouts per post.
"""

from typing import Any

from app.clients.llm.base import LlmClient, LlmResult
from app.core.breaker import CircuitBreaker


class LlmUnavailableError(Exception):
    def __init__(self, retry_in_seconds: float) -> None:
        super().__init__(f"LLM breaker open, retry in {retry_in_seconds:.0f} s")
        self.retry_in_seconds = retry_in_seconds


class GuardedLlmClient:
    def __init__(self, inner: LlmClient, breaker: CircuitBreaker) -> None:
        self.inner = inner
        self.breaker = breaker
        self.model = inner.model

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
