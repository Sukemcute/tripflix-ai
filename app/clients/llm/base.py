"""What the summary pipeline needs from an LLM provider (CHECKLIST P9).

FakeLlmClient serves tests and offline runs; the production provider is not chosen yet.
"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class LlmResult:
    output: str  # raw JSON text, checked by the validator
    model_name: str
    input_tokens: int
    output_tokens: int
    cost_usd: float = 0.0  # estimated by the adapter from token counts


class LlmClient(Protocol):
    model: str  # the configured model; joins the input hash so a model change re-summarizes

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult: ...
