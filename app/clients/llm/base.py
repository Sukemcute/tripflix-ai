"""What the summary pipeline needs from an LLM provider (CHECKLIST P9).

The real adapter (OpenAI or Claude) comes once the provider is chosen; until then the
pipeline runs end to end on FakeLlmClient.
"""

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class LlmResult:
    output: str  # raw JSON text, checked by the validator
    model_name: str
    input_tokens: int
    output_tokens: int


class LlmClient(Protocol):
    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult: ...
