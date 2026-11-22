"""Offline LLM for tests and local runs (LLM_PROVIDER=fake): returns a fixed output."""

import json
from typing import Any

from app.clients.llm.base import LlmResult

EMPTY_OUTPUT = json.dumps(
    {
        "excluded": {"video_reaction_ids": [], "speculation_ids": []},
        "safety_mentions": [],
        "pros": [],
        "cons": [],
        "reality_gaps": [],
        "topics": [],
    }
)


class FakeLlmClient:
    model = "fake"

    def __init__(self, output: str = EMPTY_OUTPUT) -> None:
        self.output = output
        self.calls = 0

    def generate(self, system: str, user: str, schema: dict[str, Any]) -> LlmResult:
        self.calls += 1
        return LlmResult(output=self.output, model_name="fake", input_tokens=0, output_tokens=0)
