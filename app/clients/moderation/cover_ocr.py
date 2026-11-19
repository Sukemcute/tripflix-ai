"""Read only the visible text on a video poster; never infer a caption."""

import base64
from typing import Any

import httpx
from pydantic import SecretStr


class CoverOcrError(Exception):
    pass


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
            response = await self.http.post("/responses", json=body, headers=self.headers)
            if response.status_code != 200:
                raise CoverOcrError(f"OCR provider returned {response.status_code}")
            payload = response.json()
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
