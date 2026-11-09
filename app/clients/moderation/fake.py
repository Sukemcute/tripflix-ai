from collections.abc import Sequence
from dataclasses import dataclass, field

from app.clients.moderation.base import ModerationResult

FAKE_MODEL = "fake-moderation"


@dataclass
class FakeModerationClient:
    """Flags any text containing one of `flag_words`; records what it was sent."""

    flag_words: tuple[str, ...] = ("FLAG",)
    error: Exception | None = None
    calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    async def moderate(self, text: str, image_urls: Sequence[str]) -> ModerationResult:
        self.calls.append((text, tuple(image_urls)))
        if self.error:
            raise self.error
        hit = any(word in text for word in self.flag_words)
        return ModerationResult(
            flagged=hit,
            categories={"harassment": hit},
            scores={"harassment": 0.9 if hit else 0.01},
            model=FAKE_MODEL,
        )
