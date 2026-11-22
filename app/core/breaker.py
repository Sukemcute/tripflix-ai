"""Circuit breaker for a dependency that can die (LLM provider, comment classifier).

After `threshold` failures in a row it opens: callers stop calling for `open_seconds` and
take their fallback at once instead of waiting on timeouts (Fowler, CircuitBreaker; research
note 04 §3). When the time is up one call goes through: success closes it, failure reopens
it. In-process only: each worker replica learns on its own, which is enough for 1-2 replicas.
"""

import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        *,
        threshold: int = 3,  # [HIỆU CHỈNH]
        open_seconds: float = 300.0,  # [HIỆU CHỈNH]
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self.threshold = threshold
        self.open_seconds = open_seconds
        self.clock = clock
        self.failures = 0
        self.open_until = 0.0

    def is_open(self) -> bool:
        return self.failures >= self.threshold and self.clock() < self.open_until

    def seconds_left(self) -> float:
        return max(0.0, self.open_until - self.clock()) if self.is_open() else 0.0

    def record_success(self) -> None:
        if self.failures >= self.threshold:
            logger.info("breaker %s closed", self.name)
        self.failures = 0

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.open_until = self.clock() + self.open_seconds
            logger.warning(
                "breaker %s open for %ss after %s failures",
                self.name,
                self.open_seconds,
                self.failures,
            )
