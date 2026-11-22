"""Observe safety signals without changing moderation decisions."""

import json
import logging
from collections.abc import Sequence

from app.clients.moderation.base import ModerationResult
from app.services.moderation import ModerationItem
from app.services.summary.lexicon import load
from app.services.summary.safety import match_safety

logger = logging.getLogger("uvicorn.error")


def log_safety_shadow(
    items: Sequence[ModerationItem], pairs: Sequence[tuple[str, ModerationResult]]
) -> None:
    try:
        version = load("safety").version
        for item, (_, result) in zip(items, pairs, strict=True):
            hit = match_safety(item.text)
            logger.info(
                "moderation.shadow %s",
                json.dumps(
                    {
                        "id": item.id,
                        "source": "safety_lexicon",
                        "version": version,
                        "categories": hit.categories if hit else [],
                        "provider_flagged": result.flagged,
                        "provider_model": result.model,
                    },
                    ensure_ascii=False,
                ),
            )
    except Exception:
        logger.exception("moderation.shadow failed")
