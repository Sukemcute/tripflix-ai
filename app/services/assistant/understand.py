"""Controller step of a chat turn: one LLM call that turns the message into JSON (TF31).

The LLM sees only the masked message and recent turns, never Core results. Each role has its
own adapter and breaker (Bảo, 2026-11-16: Controller on OpenAI, Responder on DeepSeek).
"""

import json
from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal

from app.clients.llm.base import LlmResult
from app.clients.llm.deepseek import DeepSeekClient
from app.clients.llm.fake import FakeLlmClient
from app.clients.llm.guarded import GuardedLlmClient
from app.clients.llm.openai import OpenAILlmClient
from app.core.breaker import CircuitBreaker
from app.core.config import get_chat_settings
from app.services.assistant.planner import today_in_vietnam
from app.services.assistant.schemas import ChatRequest, Understanding
from app.services.summary.pii import mask_pii
from app.services.summary.schemas import strict_json_schema

Role = Literal["controller", "responder"]
PROMPT = Path(__file__).parents[2] / "prompts" / "assistant-controller.v1.md"


class LlmNotConfiguredError(Exception):
    pass


def build_understanding_input(
    request: ChatRequest, *, max_turns: int = 6, today: date | None = None
) -> str:
    return json.dumps(
        {
            "today": (today or today_in_vietnam()).isoformat(),
            # Only whether a reel is in view: its id never reaches the LLM.
            "hasContextPost": request.context_post_id is not None,
            "message": mask_pii(request.message),
            "history": [
                {"role": turn.role, "text": mask_pii(turn.text)}
                for turn in request.history[-max_turns:]
            ],
        },
        ensure_ascii=False,
    )


@cache
def get_role_llm(role: Role) -> GuardedLlmClient:
    """One client per role per process, so connections and the breaker are shared."""
    settings = get_chat_settings()
    provider = getattr(settings, f"chat_{role}_provider")
    model = getattr(settings, f"chat_{role}_model")
    limits = {"timeout_seconds": settings.chat_llm_timeout_seconds, "max_attempts": 1}
    if provider == "fake":
        inner = FakeLlmClient()
    elif provider == "openai":
        prices = {
            "input": getattr(settings, f"chat_{role}_price_input"),
            "cached_input": getattr(settings, f"chat_{role}_price_cached_input"),
            "output": getattr(settings, f"chat_{role}_price_output"),
        }
        if not settings.openai_api_key.get_secret_value() or not model:
            raise LlmNotConfiguredError(f"{role}: OPENAI_API_KEY and model are required")
        if any(value is None for value in prices.values()):
            raise LlmNotConfiguredError(f"{role}: the three CHAT_*_PRICE_* are required")
        inner = OpenAILlmClient(
            settings.openai_api_key,
            model=model,
            prices={name: float(value) for name, value in prices.items() if value is not None},
            base_url=settings.openai_base_url,
            reasoning_effort=settings.openai_reasoning_effort,
            max_output_tokens=settings.chat_max_output_tokens,
            **limits,
        )
    else:
        if not settings.deepseek_api_key.get_secret_value():
            raise LlmNotConfiguredError(f"{role}: DEEPSEEK_API_KEY is required")
        inner = DeepSeekClient(
            settings.deepseek_api_key,
            model=model,
            base_url=settings.deepseek_base_url,
            max_output_tokens=settings.chat_max_output_tokens,
            **limits,
        )
    return GuardedLlmClient(inner, CircuitBreaker(f"chat-{role}"))


async def understand(request: ChatRequest, *, max_turns: int) -> tuple[Understanding, LlmResult]:
    """Raises on provider errors, cut output or invalid JSON: the caller falls back."""
    result = await get_role_llm("controller").agenerate(
        PROMPT.read_text(encoding="utf-8"),
        build_understanding_input(request, max_turns=max_turns),
        strict_json_schema(Understanding),
    )
    # A cut JSON can still parse into something wrong; never trust it.
    if result.finish_reason == "length":
        raise ValueError("controller output was cut")
    return Understanding.model_validate_json(result.output), result
