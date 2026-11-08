"""DeepSeek adapter (Bảo chose DeepSeek, 2026-11-05); OpenAI-format API called with httpx.

From api-docs.deepseek.com (read 2026-11-05):
- POST {base}/chat/completions, Bearer key; models deepseek-flash, deepseek-v4-pro.
- JSON output is response_format {"type": "json_object"} only, no strict schema: the prompt
  must say "json" and show the format, so the schema is appended to the system prompt and
  Pydantic checks the result (validator V1). The appended text is fixed, so the prefix stays
  cacheable (context caching is automatic, on prefixes).
- Thinking is on by default; a summary does not need it, so it is disabled (faster, no
  reasoning tokens billed).
- The API may return content made of spaces only: retried once, then left to the validator.
"""

import json
import time
from collections.abc import Callable
from typing import Any

import httpx
from pydantic import SecretStr

from app.clients.llm.base import LlmResult

DEFAULT_MODEL = "deepseek-flash"
MAX_ATTEMPTS = 3  # 1 call + 2 retries on 429/5xx or blank content
BACKOFF_SECONDS = 2.0
# USD per 1M tokens, peak hours (off-peak is half), deepseek-flash, pricing page 2026-11-05.
# shortcut: records the peak price, an upper bound; read the real bill for exact cost, and
# update when DeepSeek changes prices or another model is used.
PRICE_PER_MILLION = {"cache_hit": 0.006, "cache_miss": 0.3, "output": 1.2}


class DeepSeekClient:
    def __init__(
        self,
        api_key: SecretStr,
        *,
        model: str = DEFAULT_MODEL,
        base_url: str = "https://api.deepseek.com",
        timeout_seconds: float = 30.0,
        max_output_tokens: int = 3000,
        http: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.get_secret_value():
            raise ValueError("DEEPSEEK_API_KEY is empty")
        self.api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.max_output_tokens = max_output_tokens
        self.http = http or httpx.Client(base_url=base_url, timeout=timeout_seconds)
        self.sleep = sleep

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _with_schema(system, schema)},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "max_tokens": self.max_output_tokens,
        }
        data: dict[str, Any] = {}
        for attempt in range(1, MAX_ATTEMPTS + 1):
            response = self.http.post(
                "/chat/completions",
                json=body,
                headers={"Authorization": f"Bearer {self.api_key.get_secret_value()}"},
            )
            if _is_retryable(response) and attempt < MAX_ATTEMPTS:
                self.sleep(BACKOFF_SECONDS * attempt)
                continue
            response.raise_for_status()
            data = response.json()
            if _content(data).strip() or attempt == MAX_ATTEMPTS:
                break
        usage = data.get("usage", {})
        return LlmResult(
            output=_content(data),
            model_name=str(data.get("model", self.model)),
            input_tokens=int(usage.get("prompt_tokens", 0)),
            output_tokens=int(usage.get("completion_tokens", 0)),
            cost_usd=_cost(usage),
        )


def _with_schema(system: str, schema: dict[str, Any]) -> str:
    return (
        f"{system}\n\n# JSON schema\n\nReturn one json object valid against this JSON Schema:\n"
        f"{json.dumps(schema, ensure_ascii=False, separators=(',', ':'))}"
    )


def _is_retryable(response: httpx.Response) -> bool:
    return response.status_code == httpx.codes.TOO_MANY_REQUESTS or response.status_code >= 500


def _content(data: dict[str, Any]) -> str:
    choices = data.get("choices") or [{}]
    return str((choices[0].get("message") or {}).get("content") or "")


def _cost(usage: dict[str, Any]) -> float:
    hit = int(usage.get("prompt_cache_hit_tokens", 0))
    miss = int(usage.get("prompt_cache_miss_tokens", usage.get("prompt_tokens", 0) - hit))
    out = int(usage.get("completion_tokens", 0))
    price = PRICE_PER_MILLION
    return (hit * price["cache_hit"] + miss * price["cache_miss"] + out * price["output"]) / 1e6
