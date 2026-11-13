"""One summary run for one post (QT Bước 8-13): rules, one LLM call, validator.

Returns the body for core's PUT ai-summary, or nothing when the input hash equals the last
one (the LLM is not called again). Statuses (PRD §9.2): no_comments and insufficient_data
never call the LLM; failed means the LLM output could not be trusted.

The comment classifier, when loaded, labels once per run the comments the rules kept plus
those the safety rules flag; selection and the safety path read those labels (they rank and
flag, never drop a comment), and its version joins the input hash. No classifier (bundle
missing or broken), or a classifier that fails during the run, means the rules decide, exactly
as before: the run still finishes, and its hash says how labels were made (no classifier
version for rules only, "mixed" for part rules), so the next run with a healthy classifier
re-summarizes.
"""

import logging
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.clients.llm.base import LlmClient, LlmResult
from app.services.summary.claims import build_claims
from app.services.summary.comment_classifier import CommentClassifier, CommentLabels
from app.services.summary.estimates import PostStats, SampleShape, add_estimates
from app.services.summary.filters import filter_comments
from app.services.summary.input_hash import compute_input_hash
from app.services.summary.label_store import StoredSafety
from app.services.summary.lexicon import read_versions
from app.services.summary.pii import pseudonymize
from app.services.summary.prompt import build_user_message, load_system_prompt
from app.services.summary.safety import match_safety
from app.services.summary.sampling import pick_for_labels
from app.services.summary.schemas import (
    CommentIn,
    ItineraryItemIn,
    Labeler,
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
from app.services.summary.selection import (
    MIN_PEOPLE,
    Selection,
    decide_summary_status,
    select_comments,
)
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
# Library default; the worker passes CLASSIFIER_MAX_COMMENTS from settings (500, about 15 s at
# the 34 comments/s measured on 2 threads, BENCH_AI_SUMMARY). Over the cap a stratified weighted
# sample gets labels (sampling.py) and the rest fall back to rules.
CLASSIFIER_MAX_COMMENTS = 2_000
_SECTION_LABELS = ("Khen", "Chê", "Khác video")
# A point shares this much of its writers with a video gap -> the gap speaks for it in the
# text (share of the smaller set; proposal by Claude).
REPEAT_SHARE = 0.5


@dataclass(frozen=True)
class CheckedInput:
    """Same input as the saved summary: nothing to save, but core is told it was checked, so
    later comments that changed nothing (an emoji) do not mark the summary stale."""

    input_hash: str
    comment_count: int  # whole post's visible count, as a save would send


@dataclass(frozen=True)
class SummaryRun:
    request: SaveSummaryRequest | None  # None: same input as last run, nothing to save
    llm: LlmResult | None = None  # set when the LLM was called (cost is recorded from it)
    # labels the classifier made in this run, for the label store (replies get theirs here)
    new_labels: Mapping[str, CommentLabels] = field(default_factory=dict)
    checked: CheckedInput | None = None  # set when request is None because the hash matched


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
    classifier_max_comments: int = CLASSIFIER_MAX_COMMENTS,
    known_labels: Mapping[str, CommentLabels] | None = None,
    post_stats: PostStats | None = None,
    known_safety: Sequence[StoredSafety] = (),
    keep_labels: Callable[[Mapping[str, CommentLabels]], None] | None = None,
) -> SummaryRun:
    """known_labels: still-true labels of this classifier version from the label store; only
    the comments without one are classified, so a rerun of a big post is cheap.
    post_stats: core's whole-post counts when `comments` is its random sample.
    known_safety: safety results the label worker kept for comments outside the sample.
    keep_labels: called with this run's new labels before the LLM call, so a run the LLM then
    fails or defers does not throw away the classifier's work (it was redone every 5 min)."""
    candidates = filter_comments(comments, now).candidates
    labels: dict[str, CommentLabels] | None = None
    new: dict[str, CommentLabels] = {}
    labeler: Labeler = "rules"
    if classifier:
        # Only labels something reads: candidates (selection) and safety hits (who went).
        # Skipping the comments the rules dropped cut 25 s to 17 s on 1,000 comments (BAO_CAO).
        hits = {c.comment_id for c in comments if c.status == "visible" and match_safety(c.body)}
        wanted = {i for c in candidates for i in c.comment_ids} | hits
        known = {i: label for i, label in (known_labels or {}).items() if i in wanted}
        missing = wanted - known.keys()
        try:
            if missing:
                new = classify_comments(
                    comments,
                    classifier,
                    only=missing,
                    max_comments=classifier_max_comments,
                    first=hits & missing,
                )
        except Exception:
            # A sick classifier must not fail the summary: rules label the rest (PRD).
            logger.exception("comment classifier failed, rules used for unlabelled comments")
        labels = (known | new) or None
        if labels is not None:
            labeler = "model" if wanted <= labels.keys() else "mixed"
        if new and keep_labels:
            keep_labels(new)
    # Kept results stand for comments outside a partial sample. A comment missing from a whole
    # read is hidden or deleted, so its kept result must not come back (core's counts tell).
    is_partial = post_stats is not None and len(comments) < post_stats.comments
    safety = _rule_safety(comments, labels, known_safety if is_partial else ())
    if not comments:
        empty = SaveSummaryRequest(
            status="no_comments", safety=safety, source_comment_ids=[], generated_at=now
        )
        return SummaryRun(empty, new_labels=new)

    selection = select_comments(candidates, now, labels=labels)
    counts = SummaryCounts(
        comments=len(comments), people=selection.people, sent=len(selection.items)
    )
    # core marks a summary stale when the post's count differs from this one, so it is the
    # whole post's visible count, not the sample read (PR be #128 stats)
    comment_count = post_stats.comments if post_stats else len(comments)
    base = {
        "comment_count": comment_count,
        "safety": safety,
        "source_comment_ids": [],  # no comment text is saved until the LLM writes points
        "generated_at": now,
    }
    if decide_summary_status(len(comments), selection) == "insufficient_data":
        content = SummaryContent(
            counts=counts, needed=MIN_PEOPLE - selection.people, labeler=labeler
        )
        content = add_estimates(content, post_stats, _sample_shape(comments, selection, post_stats))
        return SummaryRun(
            SaveSummaryRequest(status="insufficient_data", content=content, **base), new_labels=new
        )

    prompt, codes = pseudonymize(selection.items)
    claims = build_claims(caption, itinerary)
    prompt_version, system = load_system_prompt()
    versions: dict[str, str | int] = {**read_versions(), "prompt": prompt_version}
    versions["model"] = llm.model
    if classifier and labels is not None:  # rules add nothing: rule-only hashes stay valid
        versions["classifier"] = classifier.version
        if labeler == "mixed":  # part rules: a healthy classifier later must re-summarize
            versions["labeler"] = labeler
    fingerprint = compute_input_hash(prompt, codes, claims, versions, safety)
    if fingerprint == previous_hash:
        return SummaryRun(None, new_labels=new, checked=CheckedInput(fingerprint, comment_count))
    failed = SaveSummaryRequest(status="failed", prompt_version=prompt_version, **base)
    if is_llm_killed:
        logger.warning("summary LLM kill switch is on")
        return SummaryRun(failed, new_labels=new)

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
        return SummaryRun(
            failed.model_copy(update={"model_name": result.model_name}), result, new_labels=new
        )

    content = _content(validated, counts).model_copy(update={"labeler": labeler})
    content = add_estimates(content, post_stats, _sample_shape(comments, selection, post_stats))
    text = _summary_text(validated)
    base["source_comment_ids"] = sorted(
        {i for s in selection.items for i in (*s.candidate.comment_ids, *s.candidate.context_ids)}
    )
    if not text:
        # Enough people, but no point had 2+ of them: nothing honest to show (proposal).
        # Keep the LLM result: the call was paid for and must be recorded. The hash goes with
        # it: without one the same input called the LLM again on every later run.
        empty = SaveSummaryRequest(
            status="insufficient_data",
            content=content,
            input_hash=fingerprint,
            prompt_version=prompt_version,
            model_name=result.model_name,
            **base,
        )
        return SummaryRun(empty, result, new_labels=new)
    request = SaveSummaryRequest(
        status="ready",
        summary=text,
        content=content,
        input_hash=fingerprint,
        prompt_version=prompt_version,
        model_name=result.model_name,
        **base,
    )
    return SummaryRun(request, result, new_labels=new)


def classify_comments(
    comments: Sequence[CommentIn],
    classifier: CommentClassifier,
    only: Collection[str] | None = None,
    max_comments: int = CLASSIFIER_MAX_COMMENTS,
    first: Collection[str] = (),
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
    if len(visible) > max_comments:
        logger.warning(
            "%s comments want labels, a sample of %s gets them", len(visible), max_comments
        )
        visible = pick_for_labels(visible, max_comments, first=first)

    def parent_text(c: CommentIn) -> str:
        if not c.parent_id:
            return ""
        if (parent := by_id.get(c.parent_id)) is None:
            return c.parent_body or ""  # parent outside the sample
        return parent.body if parent.status == "visible" else ""

    found = classifier.classify([(c.body, parent_text(c)) for c in visible])
    return {c.comment_id: label for c, label in zip(visible, found, strict=True)}


def _rule_safety(
    comments: Sequence[CommentIn],
    labels: dict[str, CommentLabels] | None,
    known: Sequence[StoredSafety] = (),
) -> SummarySafety:
    """Rule warnings: public from writers telling their own visit, pending for hearsay.
    Kept results of comments outside the sample come after, in id order (a stable hash)."""
    warnings: list[SafetyWarning] = []
    pending: list[SafetyWarning] = []
    for c in comments:
        label = labels.get(c.comment_id) if labels else None
        first_hand = label.is_first_hand if label else None
        hit = match_safety(c.body, first_hand) if c.status == "visible" else None
        if hit:
            warning = SafetyWarning(categories=list(hit.categories), comment_ids=[c.comment_id])
            (warnings if hit.visibility == "public" else pending).append(warning)
    read = {c.comment_id for c in comments}
    for k in sorted((k for k in known if k.comment_id not in read), key=lambda k: k.comment_id):
        warning = SafetyWarning(categories=list(k.categories), comment_ids=[k.comment_id])
        (warnings if k.visibility == "public" else pending).append(warning)
    return SummarySafety(warnings=warnings, pending_warnings=pending)


def _sample_shape(
    comments: Sequence[CommentIn], selection: Selection, stats: PostStats | None
) -> SampleShape:
    """Weights for estimates.py: a sent writer of tier t stands for N_t / n_t writers.
    L8 copies are no people (validator) and stand for no one here either."""
    sent = [s for s in selection.items if not s.candidate.is_suspect]
    sent_per_tier = Counter(s.tier for s in sent)
    return SampleShape(
        comments=len(comments),
        writers=len({c.author_id for c in comments if not c.is_post_author}),
        has_post_author=any(c.is_post_author for c in comments),
        is_whole=stats is not None and len(comments) >= stats.comments and selection.skipped == 0,
        weights={
            s.candidate.author_id: selection.tier_writers[s.tier - 1] / sent_per_tier[s.tier]
            for s in sent
        },
        author_of={i: s.candidate.author_id for s in sent for i in s.candidate.comment_ids},
        sent_writers=len(sent),
    )


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
