import asyncio
import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.clients.moderation.base import ModerationTimeoutError, ModerationUpstreamError
from app.clients.moderation.openai import OpenAIModerationClient

RESULT = {
    "flagged": False,
    "categories": {"harassment": False, "sexual": False},
    "category_scores": {"harassment": 0.02, "sexual": 0.01},
}


def make(handler: Any) -> OpenAIModerationClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.test/v1")
    return OpenAIModerationClient(
        SecretStr("sk-test"),
        model="omni-moderation-latest",
        base_url="unused",
        timeout_seconds=1,
        http=http,
    )


def test_text_and_images_go_in_one_request_with_the_key() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(
            200, json={"model": "omni-moderation-2024-09-26", "results": [RESULT]}
        )

    result = asyncio.run(make(handler).moderate("xin chào", ["https://cdn/a.jpg"]))

    body = json.loads(sent[0].content)
    assert sent[0].url.path == "/v1/moderations"
    assert sent[0].headers["Authorization"] == "Bearer sk-test"
    assert body == {
        "model": "omni-moderation-latest",
        "input": [
            {"type": "text", "text": "xin chào"},
            {"type": "image_url", "image_url": {"url": "https://cdn/a.jpg"}},
        ],
    }
    assert result.model == "omni-moderation-2024-09-26" and result.flagged is False


def test_several_results_merge_flags_with_or_and_scores_with_max() -> None:
    hit = {
        "flagged": True,
        "categories": {"harassment": False, "sexual": True},
        "category_scores": {"harassment": 0.01, "sexual": 0.97},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "m", "results": [RESULT, hit]})

    result = asyncio.run(make(handler).moderate("", ["https://cdn/a.jpg", "https://cdn/b.jpg"]))

    assert result.flagged is True
    assert result.categories == {"harassment": False, "sexual": True}
    assert result.scores == {"harassment": 0.02, "sexual": 0.97}


@pytest.mark.parametrize(
    ("handler", "error"),
    [
        (lambda r: httpx.Response(500, text="echo of the input"), ModerationUpstreamError),
        (lambda r: httpx.Response(200, text="not json"), ModerationUpstreamError),
        (lambda r: httpx.Response(200, json={"results": []}), ModerationUpstreamError),
        (lambda r: (_ for _ in ()).throw(httpx.ReadTimeout("slow")), ModerationTimeoutError),
        (lambda r: (_ for _ in ()).throw(httpx.ConnectError("down")), ModerationUpstreamError),
    ],
)
def test_provider_failures_map_to_two_errors(handler: Any, error: type[Exception]) -> None:
    with pytest.raises(error):
        asyncio.run(make(handler).moderate("x", []))
