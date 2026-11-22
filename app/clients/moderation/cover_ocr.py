"""Read only the visible text on a video poster; never infer a caption."""

import base64
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import SecretStr


class CoverOcrError(Exception):
    pass


@dataclass(frozen=True)
class CoverOcrTokens:
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    model: str


def read_usage(payload: dict[str, Any], fallback_model: str) -> CoverOcrTokens | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    incoming = usage.get("input_tokens")
    details = usage.get("input_tokens_details") or {}
    if not isinstance(details, dict):
        return None
    cached = details.get("cached_tokens", 0)
    outgoing = usage.get("output_tokens")
    if not isinstance(incoming, int) or isinstance(incoming, bool) or incoming < 0:
        return None
    if not isinstance(cached, int) or isinstance(cached, bool) or cached < 0:
        return None
    if not isinstance(outgoing, int) or isinstance(outgoing, bool) or outgoing < 0:
        return None
    if cached > incoming:
        return None
    model = payload.get("model")
    return CoverOcrTokens(
        incoming, cached, outgoing, model if isinstance(model, str) and model else fallback_model
    )


def estimate_cost(
    tokens: CoverOcrTokens, *, input_price: float, cached_price: float, output_price: float
) -> float:
    return (
        (tokens.input_tokens - tokens.cached_input_tokens) * input_price
        + tokens.cached_input_tokens * cached_price
        + tokens.output_tokens * output_price
    ) / 1_000_000


class OpenAICoverOcr:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        model: str,
        base_url: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self.http = http or httpx.AsyncClient(base_url=base_url, timeout=20)
        self.headers = {"Authorization": f"Bearer {api_key.get_secret_value()}"}
        self.called = False
        self.usage: CoverOcrTokens | None = None

    async def aclose(self) -> None:
        await self.http.aclose()

    async def read(self, jpeg: bytes) -> str:
        image = base64.b64encode(jpeg).decode("ascii")
        body: dict[str, Any] = {
            "model": self.model,
            "max_output_tokens": 1200,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Transcribe only text visibly printed in this image, preserving "
                                "Vietnamese accents. Do not infer, describe, translate, or add "
                                "words. Return an empty string if no text is visible."
                            ),
                        },
                        {
                            "type": "input_image",
                            "image_url": f"data:image/jpeg;base64,{image}",
                            "detail": "high",
                        },
                    ],
                }
            ],
        }
        try:
            self.called = True
            response = await self.http.post("/responses", json=body, headers=self.headers)
            if response.status_code != 200:
                raise CoverOcrError(f"OCR provider returned {response.status_code}")
            payload = response.json()
            if not isinstance(payload, dict):
                raise CoverOcrError("OCR response malformed")
            self.usage = read_usage(payload, self.model)
            if payload.get("status") != "completed":
                raise CoverOcrError("OCR response incomplete")
            fragments = [
                item.get("text")
                for output in payload.get("output", [])
                for item in output.get("content", [])
                if item.get("type") == "output_text"
            ]
            if not fragments or not all(isinstance(x, str) for x in fragments):
                raise CoverOcrError("OCR response missing text")
            text = "\n".join(fragments).strip()
            if len(text) > 5000:
                raise CoverOcrError("OCR text exceeds limit")
            return text
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise CoverOcrError("OCR provider unavailable") from exc
