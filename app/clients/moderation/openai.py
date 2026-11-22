"""OpenAI moderation adapter (omni-moderation, text and images in one request).

The endpoint is free (OpenAI, Sept 2024), takes `input` as a list of {"type": "text"} and
{"type": "image_url"} parts (URL or base64, up to 20 MB) and answers `results` with
flagged, categories and category_scores. Whether several images come back as one result or
several is not documented, so results are merged: flags OR-ed, scores max-ed.
"""

from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import SecretStr

from app.clients.moderation.base import (
    ModerationResult,
    ModerationTimeoutError,
    ModerationUpstreamError,
)


class OpenAIModerationClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        model: str,
        base_url: str,
        timeout_seconds: float,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.http = http or httpx.AsyncClient(base_url=base_url, timeout=timeout_seconds)
        self.headers = {"Authorization": f"Bearer {api_key.get_secret_value()}"}

    async def moderate(self, text: str, image_urls: Sequence[str]) -> ModerationResult:
        parts: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
        parts += [{"type": "image_url", "image_url": {"url": url}} for url in image_urls]
        try:
            response = await self.http.post(
                "/moderations", json={"model": self.model, "input": parts}, headers=self.headers
            )
        except httpx.TimeoutException as e:
            raise ModerationTimeoutError("moderation provider timed out") from e
        except httpx.HTTPError as e:
            raise ModerationUpstreamError(f"moderation provider unreachable: {e}") from e
        if response.status_code != httpx.codes.OK:
            # body may echo the input: keep only the status
            raise ModerationUpstreamError(f"moderation provider answered {response.status_code}")
        try:
            body = response.json()
            return _merge(body["results"], str(body.get("model", self.model)))
        except (ValueError, KeyError, TypeError) as e:
            raise ModerationUpstreamError("unreadable moderation response") from e

    async def aclose(self) -> None:
        await self.http.aclose()


def _merge(results: list[dict[str, Any]], model: str) -> ModerationResult:
    if not results:
        raise ValueError("no results")
    categories: dict[str, bool] = {}
    scores: dict[str, float] = {}
    for result in results:
        for name, hit in result["categories"].items():
            categories[name] = categories.get(name, False) or bool(hit)
        for name, score in result["category_scores"].items():
            scores[name] = max(scores.get(name, 0.0), float(score))
    flagged = any(bool(r["flagged"]) for r in results)
    return ModerationResult(flagged=flagged, categories=categories, scores=scores, model=model)
