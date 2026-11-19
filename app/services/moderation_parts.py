"""Independent caption/image results; an unavailable provider is never a clean verdict."""

import asyncio
from dataclasses import dataclass
from typing import Literal

from app.clients.moderation.base import ModerationClient, ModerationTimeoutError
from app.clients.moderation.visobert import VisobertModeration
from app.services.moderation import ModerationItem, moderate_items


@dataclass(frozen=True)
class PartInput:
    id: str
    kind: Literal["caption", "image"]
    text: str
    image_url: str | None


@dataclass(frozen=True)
class PartResult:
    id: str
    status: Literal["passed", "flagged", "error"]
    categories: dict[str, bool]
    scores: dict[str, float]
    model: str | None
    error_code: str | None


async def moderate_parts(
    items: list[PartInput],
    client: ModerationClient,
    timeout_seconds: float,
    visobert: VisobertModeration | None = None,
) -> list[PartResult]:
    slots = asyncio.Semaphore(4)

    async def run(item: PartInput) -> PartResult:
        async with slots:
            try:
                pairs = await moderate_items(
                    [
                        ModerationItem(
                            item.id, item.text, (item.image_url,) if item.image_url else ()
                        )
                    ],
                    client,
                    timeout_seconds,
                    visobert=visobert if item.kind == "caption" else None,
                )
                result = pairs[0][1]
                return PartResult(
                    item.id,
                    "flagged" if result.flagged else "passed",
                    result.categories,
                    result.scores,
                    result.model,
                    None,
                )
            except (ModerationTimeoutError, TimeoutError):
                return PartResult(item.id, "error", {}, {}, None, "provider_timeout")
            except Exception:
                # Provider errors may contain input URLs/text; only expose a stable error code.
                return PartResult(item.id, "error", {}, {}, None, "provider_error")

    return list(await asyncio.gather(*(run(item) for item in items)))
