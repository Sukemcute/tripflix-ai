"""OpenAI and Anthropic adapters: request shape, cost, and that build_llm picks the right one."""

import json
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.clients.llm.anthropic import AnthropicLlmClient
from app.clients.llm.deepseek import DeepSeekClient
from app.clients.llm.fake import FakeLlmClient
from app.clients.llm.openai import OpenAILlmClient
from app.core.config import Settings
from app.workers.summary_worker import build_llm

SCHEMA = {"type": "object", "properties": {"pros": {"type": "array"}}}
OUTPUT = '{"pros": []}'
PRICES = {"input": 1.0, "cached_input": 0.1, "output": 4.0}


def _openai(*responses: httpx.Response) -> tuple[OpenAILlmClient, list[httpx.Request]]:
    sent: list[httpx.Request] = []
    queue = list(responses)

    def handle(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return queue.pop(0)

    http = httpx.Client(base_url="https://api.test/v1", transport=httpx.MockTransport(handle))
    client = OpenAILlmClient(
        SecretStr("sk-test"), model="gpt-test", prices=PRICES, http=http, sleep=lambda _: None
    )
    return client, sent


def _openai_ok(content: str = OUTPUT) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "gpt-test-2026",
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 1_000_000,
                "prompt_tokens_details": {"cached_tokens": 400_000},
                "completion_tokens": 100_000,
            },
        },
    )


def test_openai_sends_a_strict_schema_and_no_deepseek_only_fields() -> None:
    client, sent = _openai(_openai_ok())

    result = client.generate("system", "user", SCHEMA)

    body = json.loads(sent[0].content)
    assert sent[0].url.path == "/v1/chat/completions"
    assert sent[0].headers["Authorization"] == "Bearer sk-test"
    assert body["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "summary", "schema": SCHEMA, "strict": True},
    }
    assert body["max_completion_tokens"] == 3000
    assert body["reasoning_effort"] == "minimal"
    assert {"thinking", "temperature", "max_tokens"}.isdisjoint(body)
    assert result.output == OUTPUT and result.model_name == "gpt-test-2026"
    # 600k fresh x 1.0 + 400k cached x 0.1 + 100k out x 4.0, per 1M
    assert result.cost_usd == pytest.approx(0.6 + 0.04 + 0.4)


def test_openai_retries_a_429_like_deepseek() -> None:
    client, sent = _openai(httpx.Response(429), _openai_ok())

    assert client.generate("s", "u", SCHEMA).output == OUTPUT
    assert len(sent) == 2


def test_openai_omits_reasoning_effort_for_models_without_reasoning() -> None:
    http = httpx.Client(
        base_url="https://api.test/v1",
        transport=httpx.MockTransport(lambda r: _openai_ok()),
    )
    client = OpenAILlmClient(
        SecretStr("sk"), model="gpt-4o-mini", prices=PRICES, reasoning_effort="", http=http
    )

    assert "reasoning_effort" not in client._body("s", "u", SCHEMA)  # pyright: ignore[reportPrivateUsage]


def test_running_out_of_tokens_is_not_retried() -> None:
    """gpt-5-nano spent its whole cap on reasoning: asking again ends the same way and pays."""
    out_of_tokens = httpx.Response(
        200,
        json={
            "model": "gpt-test",
            "choices": [{"message": {"content": ""}, "finish_reason": "length"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3000},
        },
    )
    client, sent = _openai(out_of_tokens, _openai_ok())

    assert client.generate("s", "u", SCHEMA).output == ""  # the validator turns it into failed
    assert len(sent) == 1


def test_openai_needs_a_model() -> None:
    with pytest.raises(ValueError, match="LLM_MODEL"):
        OpenAILlmClient(SecretStr("sk"), model="", prices=PRICES)


class StubMessages:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self.response


def _claude_response(stop_reason: str = "end_turn") -> Any:
    return SimpleNamespace(
        model="claude-haiku-5-5",
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=OUTPUT)],
        usage=SimpleNamespace(
            input_tokens=200_000,
            cache_read_input_tokens=700_000,
            cache_creation_input_tokens=100_000,
            output_tokens=100_000,
        ),
    )


def test_anthropic_asks_for_schema_json_at_low_effort_with_a_cached_system_prompt() -> None:
    messages = StubMessages(_claude_response())
    client = AnthropicLlmClient(SecretStr(""), client=SimpleNamespace(messages=messages))

    result = client.generate("system", "user", SCHEMA)

    [call] = messages.calls
    assert call["model"] == "claude-haiku-5-5"
    assert call["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": SCHEMA},
    }
    assert call["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "temperature" not in call and "thinking" not in call
    assert result.output == OUTPUT and result.input_tokens == 1_000_000
    # 200k x 0.10 + 700k x 0.01 + 100k x 0.125 + 100k x 0.50, per 1M
    assert result.cost_usd == pytest.approx(0.02 + 0.007 + 0.0125 + 0.05)


def test_anthropic_without_a_key_does_not_start() -> None:
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AnthropicLlmClient(SecretStr(""))


def _settings(**env: Any) -> Settings:
    return Settings(_env_file=None, **env)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize(
    ("env", "kind"),
    [
        ({"llm_provider": "fake"}, FakeLlmClient),
        ({"llm_provider": "deepseek", "deepseek_api_key": "k"}, DeepSeekClient),
        ({"llm_provider": "anthropic", "anthropic_api_key": "k"}, AnthropicLlmClient),
        (
            {
                "llm_provider": "openai",
                "openai_api_key": "k",
                "llm_model": "gpt-test",
                "llm_price_input": 1,
                "llm_price_cached_input": 0.1,
                "llm_price_output": 4,
            },
            OpenAILlmClient,
        ),
    ],
)
def test_build_llm_picks_the_adapter_from_settings(env: dict[str, Any], kind: type) -> None:
    assert type(build_llm(_settings(**env))) is kind


def test_build_llm_refuses_openai_without_prices() -> None:
    with pytest.raises(ValueError, match="LLM_PRICE_INPUT"):
        build_llm(_settings(llm_provider="openai", openai_api_key="k", llm_model="gpt-test"))
