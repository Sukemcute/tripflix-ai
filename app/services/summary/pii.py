"""Keep personal data out of the LLM prompt (QT Bước 11.1, PRD: không gửi PII sang LLM).

Real comment and author IDs become temporary codes c1..cN; the map stays in memory with
the caller. Phone numbers, emails and citizen ID numbers in the text become "[đã che]".
Like Presidio, this is pattern-based: it narrows the leak, it cannot promise zero.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.summary.selection import Selected

MASK = "[đã che]"
_SEP = r"[\s.\-]?"
_PII = [
    re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),  # email
    # Mobile: 10 digits 03/05/07/08/09 after the 2018 renumbering, or +84 without the 0.
    re.compile(rf"(?<!\d)(?:\+?84{_SEP}|0)[35789](?:{_SEP}\d){{8}}(?!\d)"),
    re.compile(rf"(?<!\d)(?:\+?84{_SEP}|0)2\d(?:{_SEP}\d){{7,8}}(?!\d)"),  # landline 02x
    # Citizen ID (CCCD): 12 digits starting with a province code 0xx (Nghị định 137/2015).
    re.compile(r"(?<!\d)0\d{11}(?!\d)"),
]
# shortcut: old 9-digit CMND, numbers spelled in words ("khong chin mot...") and account
# numbers are not caught; add patterns if seed data shows them.


@dataclass(frozen=True)
class PromptComment:
    cid: str  # temporary code sent to the LLM
    text: str  # PII masked
    is_first_hand: bool
    context: tuple[str, ...] = ()  # parent texts of replies, PII masked; not this writer's view


def mask_pii(text: str) -> str:
    for pattern in _PII:
        text = pattern.sub(MASK, text)
    return text


def pseudonymize(
    items: Sequence[Selected],
) -> tuple[list[PromptComment], dict[str, tuple[str, ...]]]:
    """Prompt-ready comments and the map from temporary code back to real comment IDs."""
    prompt: list[PromptComment] = []
    codes: dict[str, tuple[str, ...]] = {}
    for i, s in enumerate(items, start=1):
        cid = f"c{i}"
        text = mask_pii(s.text)  # the shortened text actually sent
        context = tuple(mask_pii(t) for t in s.candidate.contexts)
        prompt.append(
            PromptComment(cid=cid, text=text, is_first_hand=s.is_first_hand, context=context)
        )
        codes[cid] = s.candidate.comment_ids
    return prompt, codes
