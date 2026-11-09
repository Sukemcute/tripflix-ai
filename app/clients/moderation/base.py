"""What POST /moderate needs from a moderation provider (TF32, PRD F8).

OpenAI omni-moderation is the provider; FakeModerationClient serves tests and offline runs.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class ModerationUpstreamError(Exception):
    """The provider answered with an error or an unreadable body."""


class ModerationTimeoutError(Exception):
    """The provider did not answer in time."""


@dataclass(frozen=True)
class ModerationResult:
    flagged: bool
    categories: dict[str, bool]  # provider's own names, e.g. "harassment/threatening"
    scores: dict[str, float]
    model: str


class ModerationClient(Protocol):
    async def moderate(self, text: str, image_urls: Sequence[str]) -> ModerationResult: ...
