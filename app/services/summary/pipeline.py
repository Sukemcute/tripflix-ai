"""One summary run for one post (QT Bước 8-13): rules, one LLM call, validator.

Returns the body for core's PUT ai-summary, or nothing when the input hash equals the last
one (the LLM is not called again). Statuses (PRD §9.2): no_comments and insufficient_data
never call the LLM; failed means the LLM output could not be trusted.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.clients.llm.base import LlmClient, LlmResult
from app.services.summary.claims import build_claims
from app.services.summary.filters import filter_comments
from app.services.summary.input_hash import compute_input_hash
from app.services.summary.lexicon import read_versions
from app.services.summary.pii import pseudonymize
from app.services.summary.prompt import build_user_message, load_system_prompt
from app.services.summary.safety import match_safety
from app.services.summary.schemas import (
    CommentIn,
    ItineraryItemIn,
    RealityGapOut,
    SafetyWarning,
    SaveSummaryRequest,
    SummaryContent,
    SummaryCounts,
    SummaryPointOut,
    SummarySafety,
    TopicOut,
    build_llm_json_schema,
)
from app.services.summary.selection import MIN_PEOPLE, decide_summary_status, select_comments
from app.services.summary.validator import (
    InvalidLlmOutputError,
    SummaryPoint,
    ValidatedSummary,
    validate_summary,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SummaryRun:
    request: SaveSummaryRequest | None  # None: same input as last run, nothing to save
    llm: LlmResult | None = None  # set when the LLM was called (cost is recorded from it)


def run_summary(
    *,
    comments: Sequence[CommentIn],
    caption: str,
    itinerary: Sequence[ItineraryItemIn],
    previous_hash: str | None,
    now: datetime,
    llm: LlmClient,
    is_llm_killed: bool = False,
) -> SummaryRun:
    safety = _public_safety(comments)
    if not comments:
        return SummaryRun(SaveSummaryRequest(status="no_comments", safety=safety))

    selection = select_comments(filter_comments(comments, now).candidates, now)
    counts = SummaryCounts(
        comments=len(comments), people=selection.people, sent=len(selection.items)
    )
    base = {"comment_count": len(comments), "safety": safety}
    if decide_summary_status(len(comments), selection) == "insufficient_data":
        content = SummaryContent(counts=counts, needed=MIN_PEOPLE - selection.people)
        return SummaryRun(SaveSummaryRequest(status="insufficient_data", content=content, **base))

    prompt, codes = pseudonymize(selection.items)
    claims = build_claims(caption, itinerary)
    prompt_version, system = load_system_prompt()
    fingerprint = compute_input_hash(
        prompt, codes, claims, read_versions() | {"prompt": prompt_version}
    )
    if fingerprint == previous_hash:
        return SummaryRun(None)
    failed = SaveSummaryRequest(
        status="failed", prompt_version=prompt_version, generated_at=now, **base
    )
    if is_llm_killed:
        logger.warning("summary LLM kill switch is on")
        return SummaryRun(failed)

    result = llm.generate(system, build_user_message(prompt, claims), build_llm_json_schema())
    # shortcut: structured log until the ai.usage.recorded stream exists (CHECKLIST P9/P12).
    logger.info(
        "ai.usage.recorded",
        extra={
            "model": result.model_name,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "cost_usd": result.cost_usd,
            # compare with input_tokens to refit CHARS_PER_TOKEN for a new provider
            "estimated_comment_tokens": selection.tokens,
        },
    )
    try:
        validated = validate_summary(
            result.output, dict(zip(codes, selection.items, strict=True)), claims
        )
    except InvalidLlmOutputError:
        logger.warning("summary LLM output broke the schema", exc_info=True)
        return SummaryRun(failed.model_copy(update={"model_name": result.model_name}), result)

    content = _content(validated, counts)
    text = _summary_text(validated)
    if not text:
        # Enough people, but no point had 2+ of them: nothing honest to show (proposal).
        # Keep the LLM result: the call was paid for and must be recorded.
        empty = SaveSummaryRequest(status="insufficient_data", content=content, **base)
        return SummaryRun(empty, result)
    request = SaveSummaryRequest(
        status="ready",
        summary=text,
        content=content,
        input_hash=fingerprint,
        prompt_version=prompt_version,
        model_name=result.model_name,
        generated_at=now,
        **base,
    )
    return SummaryRun(request, result)


def _public_safety(comments: Sequence[CommentIn]) -> SummarySafety:
    """Rule warnings from writers telling their own visit; hearsay waits for a moderator."""
    warnings: list[SafetyWarning] = []
    for c in comments:
        hit = match_safety(c.body) if c.status == "visible" else None
        if hit and hit.visibility == "public":
            warnings.append(
                SafetyWarning(categories=list(hit.categories), comment_ids=[c.comment_id])
            )
    return SummarySafety(warnings=warnings)


def _content(validated: ValidatedSummary, counts: SummaryCounts) -> SummaryContent:
    def build_points(items: Sequence[SummaryPoint]) -> list[SummaryPointOut]:
        return [
            SummaryPointOut(
                aspect=p.aspect, text=p.text, comment_ids=list(p.comment_ids), people=p.people
            )
            for p in items
        ]

    return SummaryContent(
        pros=build_points(validated.pros),
        cons=build_points(validated.cons),
        reality_gaps=[
            RealityGapOut(
                claim=g.claim, reality=g.reality, comment_ids=list(g.comment_ids), people=g.people
            )
            for g in validated.reality_gaps
        ],
        topics=[
            TopicOut(
                label=t.label, summary=t.summary, comment_ids=list(t.comment_ids), people=t.people
            )
            for t in validated.topics
        ],
        counts=counts,
    )


def _summary_text(validated: ValidatedSummary) -> str:
    """Core needs a text when ready; built from validated sentences only, no free LLM text."""
    parts = [
        f"{label}: {' '.join(_sentence(t) for t in texts)}"
        for label, texts in (
            ("Khen", [p.text for p in validated.pros]),
            ("Chê", [p.text for p in validated.cons]),
            ("Khác video", [g.reality for g in validated.reality_gaps]),
        )
        if texts
    ]
    if not parts and validated.topics:
        parts.append(f"Chủ đề: {', '.join(t.label for t in validated.topics)}.")
    return " ".join(parts)


def _sentence(text: str) -> str:
    text = text.strip()
    return text if text.endswith((".", "!", "?")) else f"{text}."
