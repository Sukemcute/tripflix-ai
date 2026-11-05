"""Pick the comments sent to the LLM (QT Bước 9, BAO_CAO P6 §5): a token budget, not a fixed 120.

Tiers: 1 first-hand, 2 complaint, 3 the rest by score. Within tiers 1-2 newer comes first;
tier 3 ranks by likes, length and recency. When everything fits, everything is sent.

When it does not fit, the pick is stratified (BAO_CAO "Chọn bằng luật có làm lệch"):
complaints and the rest are drawn so the selection keeps the complaint share of all
candidates (stratified sampling, Marozzo et al. 2025; characteristic review sets, Lappas et
al. 2012). Within each stratum the tier order applies. Complaints come from the trained
classifier (complaint_model), not the lexicon: F1 0.68 vs 0.21 on labelled reviews.
An item too long for what is left is skipped, not a stop.

Fair share (BAO_CAO "Chia phần công bằng"): each comment may use at most
token_budget / target_comments tokens, so long reviews cannot crowd out other voices.
A longer comment keeps its most relevant sentences instead of being cut blindly
(pre-extraction before summarizing: Bhaskar et al. 2023; sentence-level budget: LLMLingua).
Tier, first-hand flag and safety are decided on the whole comment before it is shortened.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.services.summary import complaint_model
from app.services.summary.filters import Candidate
from app.services.summary.first_hand import detect_first_hand
from app.services.summary.lexicon import load
from app.services.summary.vi_text import count_syllables, normalize_text

# shortcut: common Vietnamese question endings only; a question without "?" or these
# endings ranks as a statement.
_QUESTION_END = re.compile(
    r"\b(?:(?:khong|ko|k|chua|vay|the) a|the nao|bao nhieu|o dau|duoc khong|co khong)$"
)
TOKEN_BUDGET = 12_000  # [HIỆU CHỈNH] set again once the LLM provider is chosen
# Safety stop only: the token budget is the real limit. Was 300, which cut short comments
# that still fit the budget (BAO_CAO). 1,000 proposed by Claude, no source.
MAX_COMMENTS = 1_000
MIN_PEOPLE = 5  # fewer distinct non-suspect writers -> insufficient_data, no LLM call
# Fitted on real usage.prompt_tokens of 83 trial calls (BAO_CAO "Ước token"): Vietnamese
# comment text costs 2.35 chars/token and each <comment> wrapper ~26 tokens. The old 3.4/8
# (o200k tokenizer) under-counted real prompts by ~1.6x. Tokenizers differ per provider
# (Petrov et al. 2023): shortcut: refit from logged usage when the provider is chosen.
CHARS_PER_TOKEN = 2.35
ITEM_OVERHEAD_TOKENS = 26
TARGET_COMMENTS = 100  # share = budget / target; [HIỆU CHỈNH] by coverage eval at P11
# Floor of a share: a comment as long as TikTok allows (150 chars, BAO_CAO L1) is never cut.
MIN_SHARE_TOKENS = math.ceil(150 / CHARS_PER_TOKEN) + ITEM_OVERHEAD_TOKENS
# Sentence ends like underthesea's rule-based splitter, plus line breaks and the " | "
# that joins one author's merged comments. shortcut: unpunctuated text stays one sentence,
# then falls back to a word-boundary cut.
_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+|\n+|\s\|\s")
# Which sentence survives first when a comment is shortened: safety, then complaints
# (classifier), then first-hand or service talk (the aspects hotel summarizers keep,
# Tsai et al. 2020). Order proposed by Claude: safety first, as in QT.
_SENTENCE_LEXICONS = (("safety", 3), ("first_hand_cues", 1), ("service_terms", 1))
COMPLAINT_SENTENCE_WEIGHT = 2
GAP = " … "  # marks dropped sentences so the LLM never reads two far-apart ones as one


@dataclass(frozen=True)
class Selected:
    candidate: Candidate
    tier: Literal[1, 2, 3]
    is_first_hand: bool
    tokens: int
    text: str  # what is sent: the comment, or its most relevant sentences within the share
    is_complaint: bool = False  # classifier label on the whole comment


@dataclass(frozen=True)
class Selection:
    items: list[Selected]
    tokens: int
    skipped: int  # candidates left out by the budget or the cap
    people: int  # distinct writers that count (L8 suspects do not)


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN) + ITEM_OVERHEAD_TOKENS


def select_comments(
    candidates: Sequence[Candidate],
    now: datetime,
    token_budget: int = TOKEN_BUDGET,
    max_comments: int = MAX_COMMENTS,
    target_comments: int = TARGET_COMMENTS,
) -> Selection:
    ranked = []
    for c in candidates:
        first_hand = detect_first_hand(c.text_norm).is_first_hand
        question = _is_question(c.text)
        complaint = is_complaint_candidate(c.text)
        tier = 1 if first_hand else 2 if complaint else 3
        newer_first = -c.created_at.timestamp()
        order = newer_first if tier < 3 else -_score(c, now)
        # suspects (L8 copies) go last in their tier, then questions: they are no opinion
        # (hotel summarizers split subjective from objective first, Tsai et al. 2020) but
        # still feed topics, so they are not dropped (Meta exempts asking for advice).
        # comment_ids make ties deterministic.
        key = (tier, c.is_suspect, question, order, c.comment_ids)
        ranked.append((key, tier, first_hand, complaint, c))
    ranked.sort(key=lambda r: r[0])

    share = max(token_budget // max(target_comments, 1), MIN_SHARE_TOKENS)
    strata = [[r for r in ranked if r[3]], [r for r in ranked if not r[3]]]
    target = len(strata[0]) / len(ranked) if ranked else 0.0  # complaint share to keep
    picked = [0, 0]
    items: list[Selected] = []
    used = 0
    while strata[0] or strata[1]:
        # draw from the stratum furthest below its share; equal deficits favour complaints
        deficits = [
            target * (sum(picked) + 1) - picked[0],
            (1 - target) * (sum(picked) + 1) - picked[1],
        ]
        k = 0 if strata[0] and (not strata[1] or deficits[0] >= deficits[1]) else 1
        _, tier, first_hand, complaint, c = strata[k].pop(0)
        text = fit_to_share(c.text, share)
        # reply context shares the same budget: more context means fewer comments, same cost
        cost = estimate_tokens(text) + sum(estimate_tokens(t) for t in c.contexts)
        if len(items) < max_comments and used + cost <= token_budget:
            items.append(
                Selected(
                    candidate=c,
                    tier=tier,
                    is_first_hand=first_hand,
                    tokens=cost,
                    text=text,
                    is_complaint=complaint,
                )
            )
            used += cost
            picked[k] += 1
    people = len({s.candidate.author_id for s in items if not s.candidate.is_suspect})
    return Selection(items=items, tokens=used, skipped=len(ranked) - len(items), people=people)


def decide_summary_status(
    total_comments: int, selection: Selection
) -> Literal["no_comments", "insufficient_data", "ready"]:
    """Gate before any LLM call. "ready" means the selection may be summarized."""
    if total_comments == 0:
        return "no_comments"
    if selection.people < MIN_PEOPLE:
        return "insufficient_data"
    return "ready"


def is_complaint_candidate(text: str) -> bool:
    """Complaint label used for strata. A question states no opinion, and the review-trained
    model scores many questions as complaints (7 of 12 on eval_300), so questions never count.
    """
    return not _is_question(text) and complaint_model.is_complaint(text)


def fit_to_share(text: str, max_tokens: int) -> str:
    """The text itself when it fits; else its best sentences, in their original order."""
    if estimate_tokens(text) <= max_tokens:
        return text
    sentences = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]
    best_first = sorted(range(len(sentences)), key=lambda i: (-_sentence_weight(sentences[i]), i))
    chosen: list[int] = []
    for i in best_first:
        if estimate_tokens(_join(sentences, sorted([*chosen, i]))) <= max_tokens:
            chosen.append(i)
    if not chosen:  # even the best sentence is too long: cut it at a word boundary
        return _cut_words(sentences[best_first[0]], max_tokens)
    return _join(sentences, sorted(chosen))


def _sentence_weight(sentence: str) -> int:
    norm = normalize_text(sentence)
    weights = [w for name, w in _SENTENCE_LEXICONS if load(name).matches(norm)]
    if complaint_model.is_complaint(sentence):
        weights.append(COMPLAINT_SENTENCE_WEIGHT)
    return max(weights, default=0)


def _join(sentences: Sequence[str], indexes: Sequence[int]) -> str:
    """Kept sentences in order; GAP wherever sentences were dropped, ends included."""
    out = GAP if indexes[0] > 0 else ""
    for k, i in enumerate(indexes):
        out += sentences[i] if k == 0 else (" " if i == indexes[k - 1] + 1 else GAP) + sentences[i]
    if indexes[-1] < len(sentences) - 1:
        out += GAP
    return out.strip()


def _cut_words(sentence: str, max_tokens: int) -> str:
    max_chars = int((max_tokens - ITEM_OVERHEAD_TOKENS) * CHARS_PER_TOKEN) - len(GAP)
    words, out = sentence.split(), ""
    for w in words:
        if len(out) + len(w) + 1 > max_chars:
            break
        out = f"{out} {w}".strip()
    return out + GAP.rstrip()


def _is_question(text: str) -> bool:
    """Every merged part of the candidate asks something and states nothing."""
    return all(
        part.rstrip().endswith("?") or bool(_QUESTION_END.search(normalize_text(part)))
        for part in text.split(" | ")
    )


def _score(c: Candidate, now: datetime) -> float:
    days = max((now - c.created_at).total_seconds() / 86_400, 0.0)
    length = min(count_syllables(c.text_norm), 60) / 60
    return math.log1p(c.like_count) + 0.5 * length + math.exp(-0.05 * days / 30)
