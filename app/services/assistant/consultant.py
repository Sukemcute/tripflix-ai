"""Consultant agent: advises where to go when the user has no destination yet (consult intent).

The LLM decides what to ask or whether to suggest, but code keeps two hard limits: it may name
only destinations of the curated catalog, and every sentence and chip passes the Verifier.
"""

import json
import logging
from collections.abc import Callable
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from app.clients.llm.base import LlmResult
from app.services.assistant.destinations import Destination, destinations_by_id, merge_prefs
from app.services.assistant.schemas import Answer, ChatRequest, TravelPrefs, TripContext
from app.services.assistant.understand import get_role_llm
from app.services.assistant.verifier import verify
from app.services.summary.pii import mask_pii
from app.services.summary.schemas import strict_json_schema

logger = logging.getLogger(__name__)
PROMPT = Path(__file__).parents[2] / "prompts" / "assistant-consultant.v1.md"
CONSULT_FACT = "consult"
HISTORY_MESSAGES = 6
MAX_SUGGESTIONS = 3
MAX_CHIPS = 4
MAX_CHIP_CHARS = 30
FALLBACK_TEXT = (
    "Bạn đang muốn một chuyến yên tĩnh để nghỉ ngơi hay sôi động cho vui? Thích biển hay núi nè?"
)
FALLBACK_CHIPS = ["Yên tĩnh, chill", "Sôi động", "Biển", "Núi"]


class ConsultOutput(BaseModel):
    # Limits (4 sentences, 3 places, 4 chips) are enforced in code: the strict schema drops them.
    sentences: list[str]
    prefs: TravelPrefs
    destination_ids: list[str]
    chips: list[str]
    is_done_asking: bool


def fallback_consult_answer() -> Answer:
    return Answer(
        kind="answer",
        text=FALLBACK_TEXT,
        suggestions=list(FALLBACK_CHIPS),
        facts=[{"type": CONSULT_FACT, "fallback": True, "hasSuggestions": False}],
    )


def _catalog_entry(destination: Destination) -> dict:
    return {
        "id": destination.id,
        "name": destination.name,
        "region": destination.region,
        "terrain": destination.terrain,
        "vibe": destination.vibe,
        "goodMonths": destination.good_months,
        "highlights": destination.highlights,
    }


def _code_chips(name: str) -> list[str]:
    return [f"Xem reel {name}", f"Tìm phòng {name}", f"Lên lịch trình {name}", "Nơi khác nha"]


async def consult(
    request: ChatRequest,
    trip: TripContext,
    *,
    today: date,
    on_usage: Callable[[LlmResult], None] | None = None,
) -> tuple[Answer, TravelPrefs]:
    """The reply and the preferences understood this turn. Raises on provider errors, broken
    JSON or a cut output: the caller then uses the fixed fallback."""
    catalog = [_catalog_entry(d) for d in destinations_by_id().values()]
    question = mask_pii(request.message)
    payload = {
        "today": today.isoformat(),
        "currentMonth": today.month,
        "message": question,
        "history": [
            {"role": turn.role, "text": mask_pii(turn.text)[:300]}
            for turn in request.history[-HISTORY_MESSAGES:]
        ],
        "prefs": trip.prefs.model_dump(mode="json", by_alias=True) if trip.prefs else None,
        "originCity": trip.origin_city,
        "catalog": catalog,
    }
    result = await get_role_llm("responder").agenerate(
        PROMPT.read_text(encoding="utf-8"),
        json.dumps(payload, ensure_ascii=False),
        strict_json_schema(ConsultOutput),
    )
    if on_usage is not None:
        on_usage(result)
    if result.finish_reason == "length":
        raise ValueError("consult output was cut")
    output = ConsultOutput.model_validate_json(result.output)

    by_id = destinations_by_id()
    ids = list(dict.fromkeys(i for i in output.destination_ids if i in by_id))[:MAX_SUGGESTIONS]
    suggested = [by_id[i] for i in ids]
    prefs_fact = {"prefs": merge_prefs(trip.prefs, output.prefs).model_dump(mode="json")}
    facts = [_catalog_entry(d) for d in suggested] if suggested else catalog
    facts = [*facts, prefs_fact]
    kwargs = {"today": today, "extra_grounding": f"{trip.origin_city} {trip.place}"}
    sentences, dropped = verify(output.sentences, facts, set(), question, **kwargs)
    if dropped:
        logger.info("chat.verifier.dropped", extra={"rules": dict(dropped)})
    if not sentences:
        logger.info("chat.consult.fallback", extra={"rules": dict(dropped)})
        return fallback_consult_answer(), output.prefs

    if suggested:
        chips = _code_chips(suggested[0].name)
    else:
        short = [c for c in output.chips if len(c) <= MAX_CHIP_CHARS]
        chips = verify(short, facts, set(), question, **kwargs)[0][:MAX_CHIPS]
    answer = Answer(
        kind="answer",
        text=" ".join(sentences),
        suggestions=chips,
        facts=[{"type": CONSULT_FACT, "hasSuggestions": bool(suggested), "destinationIds": ids}],
    )
    return answer, output.prefs
