"""Responder agent: writes the reply in Tripi's voice from this turn's facts. It has no tools,
never sees prices, and every sentence goes through the Verifier (DeepSeek, Bảo 2026-11-16)."""

import json
import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.clients.llm.base import LlmResult
from app.services.assistant.schemas import Answer, ChatRequest
from app.services.assistant.understand import get_role_llm
from app.services.assistant.verifier import REF, verify
from app.services.summary.pii import mask_pii
from app.services.summary.schemas import strict_json_schema

logger = logging.getLogger(__name__)
PROMPT = Path(__file__).parents[2] / "prompts" / "assistant-responder.v1.md"
TITLE_CHARS = 80  # titles are user-written: keep them short in the prompt
INFO_CARDS = {"itinerary", "weather", "checklist", "summary"}


class ResponderOutput(BaseModel):
    sentences: list[str] = Field(max_length=8)


def build_facts(answer: Answer) -> list[dict]:
    if answer.facts:
        return answer.facts
    # Search cards: name, kind and ref only; never the price.
    return [{"ref": c.ref, "kind": c.kind, "title": c.title[:TITLE_CHARS]} for c in answer.cards]


async def respond(request: ChatRequest, answer: Answer) -> tuple[list[str] | None, LlmResult]:
    """Sentences ready to show, or None to keep the fixed text. Raises on provider errors."""
    facts = build_facts(answer)
    question = mask_pii(request.message)
    result = await get_role_llm("responder").agenerate(
        PROMPT.read_text(encoding="utf-8"),
        json.dumps({"question": question, "facts": facts}, ensure_ascii=False),
        strict_json_schema(ResponderOutput),
    )
    if result.finish_reason == "length":
        return None, result
    sentences = ResponderOutput.model_validate_json(result.output).sentences
    kept, dropped = verify(sentences, facts, {c.ref for c in answer.cards}, question)
    if dropped:
        logger.info("chat.verifier.dropped", extra={"rules": dict(dropped)})
    if not kept:
        return None, result
    # A single info card reads better as "the card below" than as its long title.
    titles = {c.ref: "thẻ bên dưới" if c.kind in INFO_CARDS else c.title for c in answer.cards}
    return [REF.sub(lambda m: titles[m.group(1)], s) for s in kept], result


def split_for_stream(text: str) -> list[str]:
    """The fixed text, sent as sentences like the Responder's, so the app reads one shape."""
    return [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]
