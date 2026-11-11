"""OpenAI adapter (Chat Completions), httpx like the moderation client; same retry loop as
DeepSeek, which speaks the same wire format.

Differences from DeepSeek:
- response_format json_schema with strict: OpenAI checks the schema itself
  (build_llm_json_schema is written for strict mode);
- max_completion_tokens instead of max_tokens, and no temperature: reasoning models reject
  any value but the default;
- cached prompt tokens are in usage.prompt_tokens_details.cached_tokens.
No default model and no default prices: OpenAI renames models often and sources disagree on
the current list (2026-11-11), so LLM_MODEL and the LLM_PRICE_* settings must be set (cost
must be recorded for every call, RULES §10).
"""

from collections.abc import Mapping
from typing import Any

from pydantic import SecretStr

from app.clients.llm.deepseek import DeepSeekClient


class OpenAILlmClient(DeepSeekClient):
    KEY_NAME = "OPENAI_API_KEY"

    def __init__(
        self,
        api_key: SecretStr,
        *,
        model: str,
        prices: Mapping[str, float],  # USD per 1M tokens: input, cached_input, output
        base_url: str = "https://api.openai.com/v1",
        **kwargs: Any,
    ) -> None:
        if not model:
            raise ValueError("LLM_MODEL is required for openai")
        super().__init__(api_key, model=model, base_url=base_url, **kwargs)
        self.prices = dict(prices)

    def _body(self, system: str, user: str, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "summary", "schema": schema, "strict": True},
            },
            "max_completion_tokens": self.max_output_tokens,
        }

    def _cost(self, usage: dict[str, Any]) -> float:
        prompt = int(usage.get("prompt_tokens", 0))
        cached = int((usage.get("prompt_tokens_details") or {}).get("cached_tokens", 0))
        out = int(usage.get("completion_tokens", 0))
        p = self.prices
        return (
            (prompt - cached) * p["input"] + cached * p["cached_input"] + out * p["output"]
        ) / 1e6
