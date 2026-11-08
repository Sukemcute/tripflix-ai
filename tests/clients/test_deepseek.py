import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.clients.llm.deepseek import DeepSeekClient

SCHEMA = {"type": "object", "properties": {"pros": {"type": "array"}}}
OUTPUT = '{"pros": []}'


def _ok(content: str = OUTPUT) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "deepseek-flash",
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 1_000_000,
                "prompt_cache_hit_tokens": 600_000,
                "prompt_cache_miss_tokens": 400_000,
                "completion_tokens": 100_000,
            },
        },
    )


def _client(*responses: httpx.Response) -> tuple[DeepSeekClient, list[httpx.Request]]:
    sent: list[httpx.Request] = []
    queue = list(responses)

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return queue.pop(0)

    http = httpx.Client(base_url="https://api.deepseek.com", transport=httpx.MockTransport(handle))
    client = DeepSeekClient(SecretStr("sk-test"), http=http, sleep=lambda _: None)
    return client, sent


def _body(request: httpx.Request) -> dict[str, Any]:
    return json.loads(request.content)


def test_request_uses_json_mode_no_thinking_and_carries_the_schema() -> None:
    client, sent = _client(_ok())

    result = client.generate("SYSTEM", "USER", SCHEMA)

    body = _body(sent[0])
    assert sent[0].url.path == "/chat/completions"
    assert sent[0].headers["Authorization"] == "Bearer sk-test"
    assert body["model"] == "deepseek-flash"
    assert body["response_format"] == {"type": "json_object"}
    assert body["thinking"] == {"type": "disabled"}
    system = body["messages"][0]["content"]
    assert system.startswith("SYSTEM") and "json" in system and '"pros"' in system
    assert body["messages"][1] == {"role": "user", "content": "USER"}
    assert result.output == OUTPUT


def test_usage_gives_tokens_and_estimated_cost() -> None:
    client, _ = _client(_ok())

    result = client.generate("S", "U", SCHEMA)

    assert (result.input_tokens, result.output_tokens) == (1_000_000, 100_000)
    # 0.6M hit * 0.006 + 0.4M miss * 0.3 + 0.1M out * 1.2 = 0.0036 + 0.12 + 0.12
    assert result.cost_usd == pytest.approx(0.2436)


def test_rate_limit_and_blank_content_are_retried() -> None:
    client, sent = _client(httpx.Response(429), _ok("   "), _ok())

    result = client.generate("S", "U", SCHEMA)

    assert len(sent) == 3 and result.output == OUTPUT


def test_client_error_is_raised_not_retried() -> None:
    client, sent = _client(httpx.Response(401, json={"error": "bad key"}))

    with pytest.raises(httpx.HTTPStatusError):
        client.generate("S", "U", SCHEMA)
    assert len(sent) == 1


def test_missing_key_stops_early() -> None:
    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        DeepSeekClient(SecretStr(""))
