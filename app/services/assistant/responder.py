"""Responder agent: writes the reply in Tripi's voice from this turn's facts. It has no tools,
never sees prices, and every sentence goes through the Verifier (DeepSeek, Bảo 2026-11-16).

v2 (2026-11-16, Expo Web report §7.4): when code already has the direct answer (the asked
day of an itinerary, the number of days, the weather of one day, a hotel's rooms), that
"lead" goes first and the Responder only adds colour, so dropping a sentence never drops
the answer (V05, V08, W13, T25).
"""

import json
import logging
import re
from collections.abc import Callable
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field

from app.clients.llm.base import LlmResult
from app.services.assistant.schemas import Answer, ChatRequest
from app.services.assistant.understand import get_role_llm
from app.services.assistant.verifier import CARD_REF, MAX_SENTENCES, verify
from app.services.summary.pii import mask_pii
from app.services.summary.schemas import strict_json_schema
from app.services.summary.vi_text import normalize_text

logger = logging.getLogger(__name__)
PROMPT = Path(__file__).parents[2] / "prompts" / "assistant-responder.v3.md"
# The last messages, so "tại sao…" and small talk read the conversation (v3, 17/11).
HISTORY_MESSAGES = 4
TITLE_CHARS = 80  # titles are user-written: keep them short in the prompt
INFO_CARDS = {"itinerary", "weather", "checklist", "summary"}
CALL_TO_ACTION = re.compile(r"\b(bam|xem chi tiet|xem them|the ben duoi|o the)\b")


class ResponderOutput(BaseModel):
    sentences: list[str] = Field(max_length=8)


def build_facts(answer: Answer) -> list[dict]:
    if answer.facts:
        return answer.facts
    # Search cards: name, kind and ref only; never the price.
    return [{"ref": c.ref, "kind": c.kind, "title": c.title[:TITLE_CHARS]} for c in answer.cards]


def _name_refs(sentence: str, titles: dict[str, str]) -> str:
    """[r1] becomes the card's title, unless the sentence already says it ("Săn mây [r1]")."""
    said = normalize_text(sentence)

    def title(match: re.Match[str]) -> str:
        name = titles[match.group(1)]
        return "" if name and normalize_text(name) in said else name

    return CARD_REF.sub(title, sentence)


def _tidy(sentence: str) -> str:
    """Spaces and punctuation left behind by a removed card ref."""
    sentence = re.sub(r"\s+([,.!?…])", r"\1", sentence)
    sentence = re.sub(r"\s(ở|trong|xem|tại)\s*([.!?…]|$)", r"\2", sentence)
    return re.sub(r"\s{2,}", " ", sentence).strip(" ,")


def _is_call_to_action(sentence: str) -> bool:
    return bool(CALL_TO_ACTION.search(normalize_text(sentence)))


async def respond(
    request: ChatRequest,
    answer: Answer,
    *,
    today: date | None = None,
    on_usage: Callable[[LlmResult], None] | None = None,
) -> tuple[list[str] | None, LlmResult]:
    """Sentences ready to show, or None to keep the fixed text. Raises on provider errors."""
    facts = build_facts(answer)
    question = mask_pii(request.message)
    history = [
        {"role": turn.role, "text": mask_pii(turn.text)[:300]}
        for turn in request.history[-HISTORY_MESSAGES:]
    ]
    payload = {
        "question": question,
        "facts": facts,
        "alreadySaid": answer.lead,
        "history": history,
    }
    result = await get_role_llm("responder").agenerate(
        PROMPT.read_text(encoding="utf-8"),
        json.dumps(payload, ensure_ascii=False),
        strict_json_schema(ResponderOutput),
    )
    if on_usage is not None:
        on_usage(result)
    if result.finish_reason == "length":
        return None, result
    sentences = ResponderOutput.model_validate_json(result.output).sentences
    place = request.trip.place if request.trip else ""
    kept, dropped = verify(
        sentences,
        facts,
        {c.ref for c in answer.cards},
        question,
        today=today,
        extra_grounding=f"{place} {answer.lead or ''}",
    )
    if dropped:
        logger.info("chat.verifier.dropped", extra={"rules": dict(dropped)})
    # An info card is right under the text: its ref is dropped, never turned into
    # "thẻ bên dưới" in the middle of a sentence (Vũng Tàu report P2).
    titles = {c.ref: "" if c.kind in INFO_CARDS else c.title for c in answer.cards}
    kept = [_tidy(_name_refs(s, titles)) for s in kept]
    kept = [s for s in kept if s]
    if answer.lead:
        return [answer.lead, *kept][:MAX_SENTENCES], result
    if not kept:
        return None, result
    # Only "tap the card" survived: the user would get no answer, so lead with the fixed text.
    if all(_is_call_to_action(s) for s in kept):
        return [*split_for_stream(answer.text), *kept][:MAX_SENTENCES], result
    return kept, result


def split_for_stream(text: str) -> list[str]:
    """The fixed text, sent as sentences like the Responder's, so the app reads one shape."""
    return [part for part in re.split(r"(?<=[.!?])\s+", text.strip()) if part]
