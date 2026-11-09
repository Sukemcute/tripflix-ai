"""One summary run for one post (QT Bước 8-13): rules, one LLM call, validator.

Returns the body for core's PUT ai-summary, or nothing when the input hash equals the last
one (the LLM is not called again). Statuses (PRD §9.2): no_comments and insufficient_data
never call the LLM; failed means the LLM output could not be trusted.

The comment classifier, when loaded, labels once per run the comments the rules kept plus
those the safety rules flag; selection and the safety path read those labels (they rank and
flag, never drop a comment), and its version joins the input hash. No classifier (bundle
missing or broken) means the rules decide, exactly as before.
"""

import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.clients.llm.base import LlmClient, LlmResult
from app.services.summary.claims import build_claims
from app.services.summary.comment_classifier import CommentClassifier, CommentLabels
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
from app.services.summary.vi_text import normalize_text

logger = logging.getLogger(__name__)

# The text shows first in the comment box, where an AI summary sways readers most (arXiv
# 2609.14900); Apple keeps App Store review summaries at 100-300 chars. Full points stay in content.
MAX_SUMMARY_CHARS = 300
# About 2 minutes at the 15-19 comments/s measured on 2 threads (BAO_CAO). shortcut: the newest
# comments get labels, the rest fall back to rules; cache labels per comment (core or Redis,
# ask Thành) before posts with 100k comments.
CLASSIFIER_MAX_COMMENTS = 2_000
_SECTION_LABELS = ("Khen", "Chê", "Khác video")
# A point shares this much of its writers with a video gap -> the gap speaks for it in the
# text (share of the smaller set; proposal by Claude).
REPEAT_SHARE = 0.5


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
    classifier: CommentClassifier | None = None,
) -> SummaryRun:
    candidates = filter_comments(comments, now).candidates
    labels = None
    if classifier:
        # Only labels something reads: candidates (selection) and safety hits (who went).
        # Skipping the comments the rules dropped cut 25 s to 17 s on 1,000 comments (BAO_CAO).
        wanted = {i for c in candidates for i in c.comment_ids}
        wanted |= {c.comment_id for c in comments if c.status == "visible" and match_safety(c.body)}
        labels = classify_comments(comments, classifier, only=wanted)
    safety = _rule_safety(comments, labels)
    if not comments:
        return SummaryRun(SaveSummaryRequest(status="no_comments", safety=safety, generated_at=now))

    selection = select_comments(candidates, now, labels=labels)
    counts = SummaryCounts(
        comments=len(comments), people=selection.people, sent=len(selection.items)
    )
    base = {"comment_count": len(comments), "safety": safety, "generated_at": now}
    if decide_summary_status(len(comments), selection) == "insufficient_data":
        content = SummaryContent(counts=counts, needed=MIN_PEOPLE - selection.people)
        return SummaryRun(SaveSummaryRequest(status="insufficient_data", content=content, **base))

    prompt, codes = pseudonymize(selection.items)
    claims = build_claims(caption, itinerary)
    prompt_version, system = load_system_prompt()
    versions: dict[str, str | int] = read_versions() | {"prompt": prompt_version}
    if classifier:  # rules add nothing, so hashes made before the classifier stay valid
        versions["classifier"] = classifier.version
    fingerprint = compute_input_hash(prompt, codes, claims, versions)
    if fingerprint == previous_hash:
        return SummaryRun(None)
    failed = SaveSummaryRequest(status="failed", prompt_version=prompt_version, **base)
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
        **base,
    )
    return SummaryRun(request, result)


def classify_comments(
    comments: Sequence[CommentIn],
    classifier: CommentClassifier,
    only: Collection[str] | None = None,
) -> dict[str, CommentLabels]:
    """Labels for visible comments (or those in `only`), read with their parent as in training
    (comment, parent). Parents come from all comments; a hidden or deleted parent gives no
    context, like the LLM context (filters.py).
    """
    by_id = {c.comment_id: c for c in comments}
    visible = [
        c
        for c in comments
        if c.status == "visible"
        and normalize_text(c.body)
        and (only is None or c.comment_id in only)
    ]
    if len(visible) > CLASSIFIER_MAX_COMMENTS:
        logger.warning("%s comments, newest %s get labels", len(visible), CLASSIFIER_MAX_COMMENTS)
        visible = sorted(visible, key=lambda c: (c.created_at, c.comment_id), reverse=True)
        visible = visible[:CLASSIFIER_MAX_COMMENTS]

    def parent_text(c: CommentIn) -> str:
        parent = by_id.get(c.parent_id) if c.parent_id else None
        return parent.body if parent and parent.status == "visible" else ""

    found = classifier.classify([(c.body, parent_text(c)) for c in visible])
    return {c.comment_id: label for c, label in zip(visible, found, strict=True)}


def _rule_safety(
    comments: Sequence[CommentIn], labels: dict[str, CommentLabels] | None
) -> SummarySafety:
    """Rule warnings: public from writers telling their own visit, pending for hearsay."""
    warnings: list[SafetyWarning] = []
    pending: list[SafetyWarning] = []
    for c in comments:
        label = labels.get(c.comment_id) if labels else None
        first_hand = label.is_first_hand if label else None
        hit = match_safety(c.body, first_hand) if c.status == "visible" else None
        if hit:
            warning = SafetyWarning(categories=list(hit.categories), comment_ids=[c.comment_id])
            (warnings if hit.visibility == "public" else pending).append(warning)
    return SummarySafety(warnings=warnings, pending_warnings=pending)


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
    """Core needs a text when ready; built from validated sentences only, no free LLM text.

    Each point is its short form when the LLM gave a valid one (summary.v3), so 300 chars can
    hold every point; the full sentences stay in content. Points are taken in turns, the side
    more people back first, then the video gap, then the next ones, so a short text never
    keeps only one side: summaries drift in sentiment and drop caveats near the end (arXiv
    2507.03194). A pro or con resting on the same writers as a video gap is left out of the
    text: the gap says it more precisely (redundancy, as in MMR; proposal by Claude).
    """
    gaps = sorted(validated.reality_gaps, key=lambda g: -g.people)
    gap_ids = [set(g.comment_ids) for g in gaps]

    def repeats_a_gap(point: SummaryPoint) -> bool:
        ids = set(point.comment_ids)
        return any(len(ids & g) >= REPEAT_SHARE * min(len(ids), len(g)) for g in gap_ids)

    pros, cons = (
        [p for p in sorted(points, key=lambda p: -p.people) if not repeats_a_gap(p)]
        for points in (validated.pros, validated.cons)
    )
    groups = [
        [_phrase(p.short, p.text) for p in pros],
        [_phrase(p.short, p.text) for p in cons],
        [_phrase(g.short, g.reality) for g in gaps],
    ]
    cons_first = sum(p.people for p in cons) > sum(p.people for p in pros)
    order = (1, 0, 2) if cons_first else (0, 1, 2)
    picked: list[list[str]] = [[] for _ in groups]
    for rank in range(max(map(len, groups))):
        for k in order:
            if rank < len(groups[k]):
                picked[k].append(groups[k][rank])
                if len(_join_sections(picked)) > MAX_SUMMARY_CHARS:
                    picked[k].pop()  # a shorter later point may still fit
    text = _join_sections(picked)
    if not text and validated.topics:
        text = f"Chủ đề: {', '.join(t.label for t in validated.topics)}."
    return text


def _join_sections(picked: list[list[str]]) -> str:
    return " ".join(
        f"{label}: {'; '.join(phrases)}."
        for label, phrases in zip(_SECTION_LABELS, picked, strict=True)
        if phrases
    )


def _phrase(short: str | None, text: str) -> str:
    return (short or text).strip().rstrip(".!?…;").strip()
