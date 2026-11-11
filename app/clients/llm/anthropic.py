"""Anthropic adapter (Claude), official SDK `anthropic` (Bảo agreed to add it, 2026-11-11).

From the claude-api reference (models cached 2026-11-03):
- default claude-haiku-5-5 (Bảo's pick): USD 0.10 in / 0.50 out per 1M tokens for prompts up
  to 100K, about DeepSeek's price;
- output_config.format json_schema makes the first text block valid JSON for the schema
  (build_llm_json_schema is written for it), so no tool trick and no prefill;
- effort "low" and no `thinking` field: current models think adaptively, and `disabled` is
  rejected on some of them (Opus 5.5, Sonnet 5.5), so low effort is the portable way to keep
  thinking tokens down for a summary; no temperature (rejected on current models);
- the system prompt is fixed, so it carries a cache breakpoint (cache reads ~0.1x input);
- the SDK retries connection errors, 408, 409, 429 and 5xx twice (one retry layer, as for
  DeepSeek); other errors raise and the worker's bounded retry handles them.
"""

import logging
from collections.abc import Mapping
from typing import Any

import anthropic
from pydantic import SecretStr

from app.clients.llm.base import LlmResult

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-5-5"
# USD per 1M tokens for claude-haiku-5-5; cache write 1.25x and read 0.1x input. shortcut: set
# LLM_PRICE_* when LLM_MODEL is another Claude model.
DEFAULT_PRICES = {"input": 0.10, "cached_input": 0.01, "cache_write": 0.125, "output": 0.50}


class AnthropicLlmClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        model: str = DEFAULT_MODEL,
        prices: Mapping[str, float] | None = None,
        timeout_seconds: float = 30.0,
        max_output_tokens: int = 3000,
        client: Any = None,  # anthropic.Anthropic; tests pass a stub
    ) -> None:
        if client is None and not api_key.get_secret_value():
            raise ValueError("ANTHROPIC_API_KEY is empty")
        self.model = model or DEFAULT_MODEL
        self.prices = {**DEFAULT_PRICES, **(prices or {})}
        self.max_output_tokens = max_output_tokens
        self.client = client or anthropic.Anthropic(
            api_key=api_key.get_secret_value(), timeout=timeout_seconds
        )

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_output_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": "low", "format": {"type": "json_schema", "schema": schema}},
        )
        if response.stop_reason in ("refusal", "max_tokens"):
            # Not valid summary JSON: the validator turns it into `failed`, which is retried.
            logger.warning("claude stopped with %s", response.stop_reason)
        text = next((b.text for b in response.content if b.type == "text"), "")
        usage = response.usage
        read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        written = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        fresh = int(usage.input_tokens)
        out = int(usage.output_tokens)
        p = self.prices
        cost = (
            fresh * p["input"]
            + read * p["cached_input"]
            + written * p["cache_write"]
            + out * p["output"]
        ) / 1e6
        return LlmResult(
            output=text,
            model_name=str(response.model),
            input_tokens=fresh + read + written,
            output_tokens=out,
            cost_usd=cost,
        )
