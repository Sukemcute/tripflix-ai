"""Code checks every sentence the Responder wrote before the user sees it (Verifier v2).

A model that is told "do not invent" still invents sometimes, and asking another LLM to check
does not help (Huang et al., ICLR 2024). So each sentence must stand on the facts of this
turn; a failing sentence is dropped, and with none left the fixed text is used.
"""

import json
import re
from collections import Counter

from app.services.summary.vi_text import normalize_text

MAX_SENTENCES = 5
MAX_EMOJI = 2
ALWAYS_ALLOWED_NAMES = {
    "tripi",
    "tripflix",
    "thu hai",
    "thu ba",
    "thu tu",
    "thu nam",
    "thu sau",
    "thu bay",
    "chu nhat",
}

REF = re.compile(r"\[(r\d+)\]")
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
SCARCITY = re.compile(r"\b(sap het|chi con|nhanh tay|con it|chay hang|hot nhat|re nhat|gia soc)\b")
SAYS_AVAILABLE = re.compile(r"\b(con phong|con cho|con ve)\b")
SAYS_SOLD_OUT = re.compile(r"\b(het phong|het cho|het ve)\b")
CONTACT = re.compile(r"https?://|www\.|\b0\d{8,10}\b|\S+@\S+\.\w+", re.IGNORECASE)
VIETNAMESE = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", re.IGNORECASE
)
# Two or more capitalised words in a row, e.g. "Mũi Nghinh Phong".
NAME = re.compile(r"(?<!^)(?<![.!?]\s)\b([A-ZÀ-ỸĐ][\wÀ-ỹđ]*(?:\s+[A-ZÀ-ỸĐ][\wÀ-ỹđ]*)+)")
EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")


def _numbers(text: str) -> set[str]:
    return {re.sub(r"[.,]", "", n) for n in NUMBER.findall(text)}


def verify(
    sentences: list[str], facts: list[dict], refs: set[str], question: str
) -> tuple[list[str], Counter[str]]:
    facts_text = json.dumps(facts, ensure_ascii=False)
    grounded_text = f" {normalize_text(facts_text)} {normalize_text(question)} "
    allowed_numbers = _numbers(facts_text) | _numbers(question)
    availability = [f.get("available") for f in facts if isinstance(f.get("available"), bool)]
    kept: list[str] = []
    dropped: Counter[str] = Counter()
    emoji_used = 0
    for raw in sentences:
        sentence = raw.strip()
        if not sentence:
            continue
        rule = _broken_rule(sentence, refs, allowed_numbers, grounded_text, availability)
        emoji = len(EMOJI.findall(sentence))
        if rule is None and emoji_used + emoji > MAX_EMOJI:
            rule = "V7_emoji"
        if rule:
            dropped[rule] += 1
            continue
        emoji_used += emoji
        kept.append(sentence)
        if len(kept) == MAX_SENTENCES:
            break
    return kept, dropped


def _broken_rule(
    sentence: str,
    refs: set[str],
    allowed_numbers: set[str],
    grounded_text: str,
    availability: list[bool | None],
) -> str | None:
    if any(ref not in refs for ref in REF.findall(sentence)):
        return "V1_unknown_ref"
    without_refs = REF.sub(" ", sentence)
    if not _numbers(without_refs) <= allowed_numbers:
        return "V2_ungrounded_number"
    for name in NAME.findall(without_refs):
        folded = normalize_text(name)
        if folded not in ALWAYS_ALLOWED_NAMES and f" {folded} " not in grounded_text:
            return "V3_ungrounded_name"
    norm = normalize_text(sentence)
    if SCARCITY.search(norm):
        return "V4_scarcity"
    if SAYS_AVAILABLE.search(norm) and availability and not any(availability):
        return "V5_availability"
    if SAYS_SOLD_OUT.search(norm) and any(availability):
        return "V5_availability"
    if CONTACT.search(sentence):
        return "V6_contact"
    if not VIETNAMESE.search(sentence):
        return "V7_language"
    return None
