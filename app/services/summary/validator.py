"""Validator V1-V8 (QT Bước 13): only what code can check reaches the summary card.

Runs after the LLM, before anything is stored. LLM-based checks only measure, they are no
guardrail (RN ai_guardrails_evaluation §1), so every check here is a rule:
- V1 schema, and every id must be one the prompt carried (citation existence, as in
  CiteFix and VeriCite: drop citations outside the source set).
- V2/V5 evidence from excluded or safety-flagged comments is dropped. Safety reaches the
  card only from rules (P5); a hearsay warning held for a moderator must not slip out as
  a con or a topic written by the LLM.
- V3/V8 a point needs 2+ different people (Amazon: several customers must share it).
- V4 reality gaps merge per claim, then need 2+ first-hand writers.
- V6 people are counted by code; a sentence with a count, a share, money or PII is dropped.
When the LLM writes more points than the card holds, every item is checked first and the cap
is filled by coverage, not by position: one point per aspect, most people first, then the
next ones (key points chosen for coverage without redundancy, Bar-Haim et al. 2021; MMR,
Carbonell & Goldstein 1998; aspects ranked by how often they are raised, Hu & Liu 2004).
Keeping the first five lost whole aspects on a 1,000-comment post (BAO_CAO).
V7 (season from bookings) is gone: comments are no longer tied to bookings.
"""

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

from pydantic import ValidationError

from app.services.summary.claims import Claim
from app.services.summary.lexicon import load
from app.services.summary.pii import mask_pii
from app.services.summary.safety import match_safety
from app.services.summary.schemas import (
    MAX_EVIDENCE,
    MAX_POINTS,
    MAX_REALITY_GAPS,
    MAX_SAFETY_MENTIONS,
    MAX_TOPICS,
    SHORT_CHARS,
    Aspect,
    AspectPoint,
    RealityGap,
    SummaryLlmOutput,
    Topic,
)
from app.services.summary.selection import Selected
from app.services.summary.vi_text import normalize_text

MIN_PEOPLE_PER_POINT = 2  # V3/V4/V8; same threshold the read path re-checks (QT §15)
# normalize_text strips symbols, so "70%" or "$20" are checked on the raw sentence.
_SYMBOL_NUMBER = re.compile(r"\d\s*[%$₫€]|[$₫€]\s*\d")

Section = Literal["excluded", "safety_mentions", "pros", "cons", "reality_gaps", "topics"]
Action = Literal["drop_id", "drop_item", "drop_short", "merge", "trim"]


class InvalidLlmOutputError(ValueError):
    """V1: the output is not the schema; the whole run fails."""


@dataclass(frozen=True)
class Finding:
    rule: str  # V1..V8
    section: Section
    action: Action
    detail: str


@dataclass(frozen=True)
class SummaryPoint:
    aspect: Aspect
    text: str
    comment_ids: tuple[str, ...]  # real ids
    people: int
    short: str | None = None  # a few words for the summary text; None -> the text is used


@dataclass(frozen=True)
class RealityGapPoint:
    claim_id: str
    claim: str
    reality: str
    comment_ids: tuple[str, ...]
    people: int  # first-hand writers only
    short: str | None = None


@dataclass(frozen=True)
class TopicPoint:
    label: str
    summary: str
    comment_ids: tuple[str, ...]
    people: int


@dataclass(frozen=True)
class ValidatedSummary:
    pros: list[SummaryPoint]
    cons: list[SummaryPoint]
    reality_gaps: list[RealityGapPoint]
    topics: list[TopicPoint]
    # Comments the LLM saw as safety issues but the rules did not flag: never shown, they
    # go to review to grow the safety lexicon (QT V5, proposal of v1.1).
    safety_hints: tuple[str, ...]
    report: list[Finding]  # every drop and merge, with its rule (validator_report)


def validate_summary(
    raw_output: str, by_code: Mapping[str, Selected], claims: Sequence[Claim]
) -> ValidatedSummary:
    """Check the LLM output against what was sent. by_code maps c1..cN to the selection."""
    data, overflow, trims = _trim_overflow(raw_output)
    try:
        output = SummaryLlmOutput.model_validate(data)
    except ValidationError as e:
        raise InvalidLlmOutputError(str(e)) from e
    # Overflow items skip the schema's maxItems but each is checked like the others; a broken
    # extra is dropped, it never fails the run.
    extras: dict[Section, list[Any]] = {}
    for section, items in overflow.items():
        model = _ITEM_MODELS[section]
        for item in items:
            try:
                extras.setdefault(section, []).append(model.model_validate(item))
            except ValidationError:
                trims.append(Finding("V1", section, "drop_item", "extra item breaks the schema"))
    output = output.model_copy(update={k: [*getattr(output, k), *v] for k, v in extras.items()})
    validator = _Validator(by_code, claims)
    validator.report += trims
    return validator.run(output)


_SECTION_CAPS: dict[Section, int] = {
    "safety_mentions": MAX_SAFETY_MENTIONS,
    "pros": MAX_POINTS,
    "cons": MAX_POINTS,
    "reality_gaps": MAX_REALITY_GAPS,
    "topics": MAX_TOPICS,
}


_ITEM_MODELS: dict[Section, type[AspectPoint | RealityGap | Topic]] = {
    "pros": AspectPoint,
    "cons": AspectPoint,
    "reality_gaps": RealityGap,
    "topics": Topic,
}
# Items read past the cap before picking by coverage; a runaway output stops here.
OVERFLOW_FACTOR = 3


def _trim_overflow(raw_output: str) -> tuple[Any, dict[Section, list[Any]], list[Finding]]:
    """V1: too many items or ids, or a list section left out, never fail the run; anything
    else wrong (broken JSON, wrong types, unknown aspect, extra field, no `excluded`) still does.

    Ranked sections keep their overflow (up to OVERFLOW_FACTOR x cap) for _select; safety
    mentions and ids keep the first N. A JSON mode without a strict schema ignores maxItems
    and required: in a real LLM trial, 22 of 47 real runs failed only for an extra item or id,
    and the 1,000-comment post once failed only because `topics` was missing (BAO_CAO).
    A missing list reads as empty, which the prompt allows; `excluded` stays required since it
    removes evidence.
    """
    try:
        data: Any = json.loads(raw_output)
    except json.JSONDecodeError as e:
        raise InvalidLlmOutputError(f"not JSON: {e}") from e
    findings: list[Finding] = []
    overflow: dict[Section, list[Any]] = {}
    if not isinstance(data, dict):
        return data, overflow, findings
    sections = cast(dict[str, Any], data)
    for section, cap in _SECTION_CAPS.items():
        if section not in sections:
            findings.append(Finding("V1", section, "trim", "missing, read as empty"))
            sections[section] = []
        items = sections.get(section)
        if not isinstance(items, list):
            continue
        items = cast(list[Any], items)
        limit = cap * OVERFLOW_FACTOR if section in _ITEM_MODELS else cap
        if len(items) > limit:
            findings.append(Finding("V1", section, "trim", f"{len(items)} items, kept {limit}"))
            items = items[:limit]
        sections[section] = items[:cap]
        if len(items) > cap:
            overflow[section] = items[cap:]
        for item in items:
            ids = cast(dict[str, Any], item).get("comment_ids") if isinstance(item, dict) else None
            if isinstance(ids, list) and len(cast(list[Any], ids)) > MAX_EVIDENCE:
                findings.append(
                    Finding(
                        "V1",
                        section,
                        "trim",
                        f"{len(cast(list[Any], ids))} ids, kept {MAX_EVIDENCE}",
                    )
                )
                cast(dict[str, Any], item)["comment_ids"] = cast(list[Any], ids)[:MAX_EVIDENCE]
    return data, overflow, findings


class _Validator:
    def __init__(self, by_code: Mapping[str, Selected], claims: Sequence[Claim]) -> None:
        self.by_code = by_code
        self.claims = {c.id: c.text for c in claims}
        self.flagged = {code for code, s in by_code.items() if match_safety(s.candidate.text)}
        self.report: list[Finding] = []

    def run(self, output: SummaryLlmOutput) -> ValidatedSummary:
        excluded_ids = output.excluded.video_reaction_ids + output.excluded.speculation_ids
        self.excluded = set(self._known("excluded", excluded_ids))
        hints = (
            c
            for m in output.safety_mentions
            for c in self._known("safety_mentions", m.comment_ids)
            if c not in self.flagged
        )
        return ValidatedSummary(
            pros=self._select("pros", self._points("pros", output.pros), MAX_POINTS),
            cons=self._select("cons", self._points("cons", output.cons), MAX_POINTS),
            reality_gaps=self._select("reality_gaps", self._reality_gaps(output), MAX_REALITY_GAPS),
            topics=self._select("topics", self._topics(output), MAX_TOPICS),
            safety_hints=self._real_ids(dict.fromkeys(hints)),
            report=self.report,
        )

    def _points(self, section: Section, items: Sequence[AspectPoint]) -> list[SummaryPoint]:
        points: list[SummaryPoint] = []
        for item in items:
            codes = self._evidence(section, item.comment_ids)
            people = self._people(codes)
            if self._is_kept(section, item.text, codes, people, "V3", [item.text]):
                short = self._short(section, item.short)
                points.append(
                    SummaryPoint(item.aspect, item.text, self._real_ids(codes), people, short)
                )
        return points

    def _short(self, section: Section, short: str | None) -> str | None:
        """V6 on the short form too; a bad one only falls back to the full text."""
        short = (short or "").strip()
        if not short:
            return None
        reason = "too long" if len(short) > SHORT_CHARS else find_banned_reason(short)
        if reason:
            self._note("V6", section, "drop_short", f"{reason}: {short}")
            return None
        return short

    def _reality_gaps(self, output: SummaryLlmOutput) -> list[RealityGapPoint]:
        # V4: merge first, so a claim split into two 1-person items is not lost twice.
        merged: dict[str, tuple[list[str], str, str | None, int]] = {}
        for gap in output.reality_gaps:
            if gap.claim_id not in self.claims:
                self._note("V1", "reality_gaps", "drop_item", f"unknown claim {gap.claim_id}")
                continue
            codes = self._evidence("reality_gaps", gap.comment_ids)
            if gap.claim_id in merged:
                self._note("V4", "reality_gaps", "merge", gap.claim_id)
                old_codes, old_text, old_short, old_size = merged[gap.claim_id]
                text, short = (
                    (gap.reality, gap.short) if len(codes) > old_size else (old_text, old_short)
                )
                merged[gap.claim_id] = (old_codes + codes, text, short, max(len(codes), old_size))
            else:
                merged[gap.claim_id] = (codes, gap.reality, gap.short, len(codes))
        gaps: list[RealityGapPoint] = []
        for claim_id, (codes, reality, short, _) in merged.items():
            first_hand = [c for c in dict.fromkeys(codes) if self.by_code[c].is_first_hand]
            for code in set(codes) - set(first_hand):
                self._note("V4", "reality_gaps", "drop_id", f"{code} not first-hand")
            people = self._people(first_hand, should_count_supporters=False)
            if self._is_kept("reality_gaps", reality, first_hand, people, "V4", [reality]):
                gaps.append(
                    RealityGapPoint(
                        claim_id,
                        self.claims[claim_id],
                        reality,
                        self._real_ids(first_hand),
                        people,
                        self._short("reality_gaps", short),
                    )
                )
        return gaps

    def _topics(self, output: SummaryLlmOutput) -> list[TopicPoint]:
        # V8: topics with the same label after normalization are one topic.
        merged: dict[str, tuple[str, str, list[str], int]] = {}
        for topic in output.topics:
            codes = self._evidence("topics", topic.comment_ids)
            key = normalize_text(topic.label)
            if key in merged:
                self._note("V8", "topics", "merge", topic.label)
                label, summary, old_codes, old_size = merged[key]
                if len(codes) > old_size:
                    label, summary = topic.label, topic.summary
                merged[key] = (label, summary, old_codes + codes, max(len(codes), old_size))
            else:
                merged[key] = (topic.label, topic.summary, codes, len(codes))
        topics: list[TopicPoint] = []
        for label, summary, codes, _ in merged.values():
            codes = list(dict.fromkeys(codes))
            people = self._people(codes)
            if self._is_kept("topics", label, codes, people, "V8", [label, summary]):
                topics.append(TopicPoint(label, summary, self._real_ids(codes), people))
        return topics

    def _select[T: (SummaryPoint, RealityGapPoint, TopicPoint)](
        self, section: Section, items: list[T], cap: int
    ) -> list[T]:
        """Fill the cap by coverage: first the best-backed item of each aspect, most people
        first, then the rest by people; ties keep the LLM's order. Gaps and topics are already
        merged per claim and label, so each is its own key."""
        if len(items) <= cap:
            return items
        by_people = sorted(range(len(items)), key=lambda i: -items[i].people)
        seen: set[object] = set()
        first: list[int] = []
        rest: list[int] = []
        for i in by_people:
            item = items[i]
            key: object = item.aspect if isinstance(item, SummaryPoint) else i
            (rest if key in seen else first).append(i)
            seen.add(key)
        kept = (first + rest)[:cap]
        dropped = [_name(items[i]) for i in by_people if i not in kept]
        self._note("V1", section, "trim", f"{len(items)} items, kept {cap}: dropped {dropped}")
        return [items[i] for i in kept]

    def _evidence(self, section: Section, codes: Iterable[str]) -> list[str]:
        """V1 known ids, V2 not excluded, V5 not safety-flagged; deduplicated, in order."""
        kept: list[str] = []
        for code in dict.fromkeys(self._known(section, codes)):
            if code in self.excluded:
                self._note("V2", section, "drop_id", f"{code} excluded")
            elif code in self.flagged:
                self._note("V5", section, "drop_id", f"{code} safety-flagged")
            else:
                kept.append(code)
        return kept

    def _known(self, section: Section, codes: Iterable[str]) -> list[str]:
        known: list[str] = []
        for code in codes:
            if code in self.by_code:
                known.append(code)
            else:
                self._note("V1", section, "drop_id", f"{code} not in the prompt")
        return known

    def _is_kept(
        self,
        section: Section,
        name: str,
        codes: Sequence[str],
        people: int,
        rule: str,
        texts: Sequence[str],
    ) -> bool:
        if people < MIN_PEOPLE_PER_POINT or not codes:
            self._note(rule, section, "drop_item", f"{people} people: {name}")
            return False
        banned = next((reason for t in texts if (reason := find_banned_reason(t))), None)
        if banned:
            self._note("V6", section, "drop_item", f"{banned}: {name}")
            return False
        return True

    def _people(self, codes: Iterable[str], *, should_count_supporters: bool = True) -> int:
        """Distinct writers; L8 suspects do not count. Agreeing repliers count for V3/V8."""
        people: set[str] = set()
        for code in codes:
            candidate = self.by_code[code].candidate
            if candidate.is_suspect:
                continue
            people.add(candidate.author_id)
            if should_count_supporters:
                people |= candidate.supporters
        return len(people)

    def _real_ids(self, codes: Iterable[str]) -> tuple[str, ...]:
        return tuple(i for code in codes for i in self.by_code[code].candidate.comment_ids)

    def _note(self, rule: str, section: Section, action: Action, detail: str) -> None:
        self.report.append(Finding(rule, section, action, detail))


def _name(item: SummaryPoint | RealityGapPoint | TopicPoint) -> str:
    if isinstance(item, SummaryPoint):
        return f"{item.aspect} ({item.people})"
    if isinstance(item, RealityGapPoint):
        return f"{item.claim_id} ({item.people})"
    return f"{item.label} ({item.people})"


def find_banned_reason(text: str) -> str | None:
    """V6: counts, shares and money are the code's job; PII must never be shown."""
    hit = load("summary_bans").matches(normalize_text(text))
    if hit:
        return hit[0]
    if _SYMBOL_NUMBER.search(text):
        return "symbol_number"
    if mask_pii(text) != text:
        return "pii"
    return None
