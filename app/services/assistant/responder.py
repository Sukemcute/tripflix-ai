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
from datetime import date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from app.clients.llm.base import LlmResult
from app.services.assistant.calendar import build_calendar, responder_calendar
from app.services.assistant.schemas import Answer, ChatRequest
from app.services.assistant.social import is_off_topic_answer, was_said
from app.services.assistant.understand import get_role_llm, resolve_now
from app.services.assistant.verifier import CARD_REF, MAX_SENTENCES, verify
from app.services.summary.pii import mask_pii
from app.services.summary.schemas import strict_json_schema
from app.services.summary.vi_text import normalize_text

logger = logging.getLogger(__name__)
PROMPT = Path(__file__).parents[2] / "prompts" / "assistant-responder.v5.md"
# The last messages, so "tại sao…" and small talk read the conversation (v3, 17/11).
HISTORY_MESSAGES = 4
TITLE_CHARS = 80  # titles are user-written: keep them short in the prompt
INFO_CARDS = {"itinerary", "weather", "checklist", "summary"}
FIXED_KINDS = {"clarify", "no_result"}
FIXED_MAX_SENTENCES = 2
CALL_TO_ACTION = re.compile(r"\b(bam|xem chi tiet|xem them|the ben duoi|o the)\b")


class ResponderOutput(BaseModel):
    sentences: list[str] = Field(max_length=8)


def build_facts(answer: Answer) -> list[dict]:
    if answer.facts:
        return answer.facts
    if not answer.cards and answer.kind in FIXED_KINDS:
        # Code's own sentence: the Responder only rewords it, never adds content.
        return [{"type": "fixed", "answerKind": answer.kind, "fallback": answer.text}]
    # Search cards: name, kind and ref only; a skill that may name prices sets answer.facts.
    return [{"ref": c.ref, "kind": c.kind, "title": c.title[:TITLE_CHARS]} for c in answer.cards]


def _name_refs(sentence: str, titles: dict[str, str]) -> str:
    """[r1] becomes the card's title, unless the sentence already says it ("Săn mây [r1]").

    When the words before the ref are only the start of the title ("An Homestay [r2]" for
    "An Homestay Vũng Tàu"), those words and the ref become the full title, not a repeat.
    """
    said = normalize_text(sentence)
    out: list[str] = []
    last = 0
    for match in CARD_REF.finditer(sentence):
        name = titles[match.group(1)]
        words = normalize_text(name).split()
        before = [
            (token, normalize_text(token.group()))
            for token in re.finditer(r"\S+", sentence[last : match.start()])
        ]
        prefix = next(
            (
                size
                for size in range(min(len(words) - 1, len(before)), 0, -1)
                if [folded for _, folded in before[-size:]] == words[:size]
            ),
            0,
        )
        if name and normalize_text(name) in said:
            replacement, start = "", match.start()
        elif prefix:
            replacement, start = name, last + before[-prefix][0].start()
        else:
            replacement, start = name, match.start()
        out += [sentence[last:start], replacement]
        last = match.end()
    return "".join(out) + sentence[last:]


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
    now: datetime | None = None,
    on_usage: Callable[[LlmResult], None] | None = None,
) -> tuple[list[str] | None, LlmResult]:
    """Sentences ready to show, or None to keep the fixed text. Raises on provider errors."""
    facts = build_facts(answer)
    calendar = build_calendar(resolve_now(now, today))
    question = mask_pii(request.message)
    history = [
        {"role": turn.role, "text": mask_pii(turn.text)[:300]}
        for turn in request.history[-HISTORY_MESSAGES:]
    ]
    payload = {
        "question": question,
        "facts": facts,
        "calendar": responder_calendar(calendar),
        "alreadySaid": answer.lead,
        "editApplied": answer.edit_applied,
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
        edit_applied=answer.edit_applied,
        calendar=calendar,
    )
    if dropped:
        logger.info("chat.verifier.dropped", extra={"rules": dict(dropped)})
    # An info card is right under the text: its ref is dropped, never turned into
    # "thẻ bên dưới" in the middle of a sentence (Vũng Tàu report P2).
    titles = {c.ref: "" if c.kind in INFO_CARDS else c.title for c in answer.cards}
    kept = [_tidy(_name_refs(s, titles)) for s in kept]
    kept = [s for s in kept if s]
    if is_off_topic_answer(answer):
        kept = kept[:2]
        text = " ".join(kept)
        folded = normalize_text(text)
        destination = next((f.get("place") for f in facts if f.get("offTopic")), "")
        if (
            not kept
            or not re.search(r"\bkhong\b", folded)
            or not re.search(
                r"\b(du lich|chuyen di|lich trinh|chuyen|di choi|diem den)\b",
                normalize_text(kept[-1]),
            )
            or was_said(text, request.history)
            or (destination and normalize_text(destination) not in normalize_text(kept[-1]))
        ):
            return None, result
        return kept, result
    if any(f.get("type") == "fixed" for f in facts):
        kept = kept[:FIXED_MAX_SENTENCES]
        is_question_missing = answer.kind == "clarify" and not any(
            re.search(r"\?\W*$", s) for s in kept
        )
        return (None if not kept or is_question_missing else kept), result
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
