"""Moderation of posts and comments for core (TF32, PRD F8: regex in core + this model check).

Core calls with a 3 s timeout and runs its regex step whatever happens here, so a failure
fails the whole request (no half results). Nothing is stored. Phones, e-mails, ID numbers
and person names are masked before the text leaves for the provider (PRD: no PII to the
LLM); spam with phone numbers is core's regex job.
"""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from app.clients.moderation.base import ModerationClient, ModerationResult, ModerationTimeoutError
from app.services.summary.pii import mask_pii

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModerationItem:
    id: str
    text: str
    image_urls: tuple[str, ...]


async def moderate_items(
    items: Sequence[ModerationItem], client: ModerationClient, timeout_seconds: float
) -> list[tuple[str, ModerationResult]]:
    """One provider call per item, all at once, within one deadline."""
    try:
        async with asyncio.timeout(timeout_seconds):
            results = await asyncio.gather(
                *(client.moderate(mask_pii(i.text), i.image_urls) for i in items)
            )
    except TimeoutError as e:
        raise ModerationTimeoutError("moderation took longer than the deadline") from e
    # shortcut: structured log until the ai.usage.recorded stream exists (as in the summary).
    logger.info(
        "ai.usage.recorded",
        extra={
            "feature": "moderation",
            "model": results[0].model if results else "",
            "items": len(items),
            "images": sum(len(i.image_urls) for i in items),
            "cost_usd": 0.0,  # OpenAI moderation is free
        },
    )
    return [(item.id, result) for item, result in zip(items, results, strict=True)]
