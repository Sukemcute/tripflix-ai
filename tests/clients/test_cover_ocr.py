import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from app.clients.moderation.cover_ocr import CoverOcrError, OpenAICoverOcr, estimate_cost


def test_reads_only_poster_text_and_keeps_vietnamese() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "gpt-4.1-mini"
        assert body["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "model": "gpt-4.1-mini-2025-04-14",
                "usage": {
                    "input_tokens": 1000,
                    "output_tokens": 20,
                    "input_tokens_details": {"cached_tokens": 200},
                },
                "output": [{"content": [{"type": "output_text", "text": "Chào Việt Nam"}]}],
            },
        )

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(handler), base_url="https://api.test"
        ) as http:
            ocr = OpenAICoverOcr(
                SecretStr("test"), model="gpt-4.1-mini", base_url="https://api.test", http=http
            )
            assert await ocr.read(b"\xff\xd8\xff\xd9") == "Chào Việt Nam"
            assert ocr.called is True
            assert ocr.usage is not None
            assert ocr.usage.model == "gpt-4.1-mini-2025-04-14"
            assert estimate_cost(
                ocr.usage, input_price=0.4, cached_price=0.1, output_price=1.6
            ) == pytest.approx(0.000372)

    asyncio.run(run())


def test_incomplete_response_is_not_a_clean_poster() -> None:
    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"status": "incomplete", "output": []})
            ),
            base_url="https://api.test",
        ) as http:
            ocr = OpenAICoverOcr(
                SecretStr("test"), model="gpt-4.1-mini", base_url="https://api.test", http=http
            )
            with pytest.raises(CoverOcrError):
                await ocr.read(b"\xff\xd8\xff\xd9")

    asyncio.run(run())
