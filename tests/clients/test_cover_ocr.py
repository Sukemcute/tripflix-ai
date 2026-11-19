import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from app.clients.moderation.cover_ocr import CoverOcrError, OpenAICoverOcr


def test_reads_only_poster_text_and_keeps_vietnamese() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "gpt-4.1-mini"
        assert body["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
        return httpx.Response(
            200,
            json={
                "status": "completed",
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
