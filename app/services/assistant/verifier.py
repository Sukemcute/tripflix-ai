"""Code checks every sentence the Responder wrote before the user sees it (Verifier v3).

A model that is told "do not invent" still invents sometimes, and asking another LLM to check
does not help (Huang et al., ICLR 2024). So each sentence must stand on the facts of this
turn; a failing sentence is dropped, and with none left the fixed text is used.

v3 (2026-11-16, Expo Web report §7.4): names are checked word by word, since 35 of 37
dropped sentences were good ones lost to the exact-phrase rule; weather numbers must belong
to the day the sentence names (V8, T20, W14); at most 4 sentences, as the prompt says.
"""

import json
import re
from collections import Counter
from datetime import date, timedelta

from app.services.summary.vi_text import normalize_text

MAX_SENTENCES = 4
MAX_EMOJI = 2
EDIT_CLAIM = re.compile(
    r"\b(?:(?:da|vua)\s+(?:doi|sua|xep lai|chuyen|bo|them)|"
    r"(?:doi lai|sua lai|xep lai|chuyen lai|doi thu tu|dao lai)\b[^.!?…]*\broi)\b"
)
# Weekday names ("Thứ Bảy", "Chủ nhật") and app words are never invented places.
ALWAYS_ALLOWED_WORDS = {
    "tripi",
    "tripflix",
    "thu",
    "hai",
    "ba",
    "tu",
    "nam",
    "sau",
    "bay",
    "chu",
    "nhat",
    "ngay",
    "dem",
}

REF = re.compile(r"\[(r\d+)\]")
# "thẻ [r1]" must not become "thẻ thẻ bên dưới" (Expo Web report T24).
CARD_REF = re.compile(r"(?:thẻ\s+)?\[(r\d+)\]", re.IGNORECASE)
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/\d{2,4})?\b")
SCARCITY = re.compile(r"\b(sap het|chi con|nhanh tay|con it|chay hang|hot nhat|re nhat|gia soc)\b")
SAYS_AVAILABLE = re.compile(r"\b(con phong|con cho|con ve)\b")
SAYS_SOLD_OUT = re.compile(r"\b(het phong|het cho|het ve)\b")
CONTACT = re.compile(r"https?://|www\.|\b0\d{8,10}\b|\S+@\S+\.\w+", re.IGNORECASE)
VIETNAMESE = re.compile(
    r"[àáảãạăằắẳẵặâầấẩẫậèéẻẽẹêềếểễệìíỉĩịòóỏõọôồốổỗộơờớởỡợùúủũụưừứửữựỳýỷỹỵđ]", re.IGNORECASE
)
# Two or more capitalised words in a row, e.g. "Mũi Nghinh Phong".
WORD = re.compile(r"[^\W\d_]+")
EMOJI = re.compile("[\U0001f300-\U0001faff☀-➿]")
WEEKDAY_WORDS = {
    0: ("thu hai", "t2"),
    1: ("thu ba", "t3"),
    2: ("thu tu", "t4"),
    3: ("thu nam", "t5"),
    4: ("thu sau", "t6"),
    5: ("thu bay", "t7"),
    6: ("chu nhat", "cn"),
}


def _numbers(text: str) -> set[str]:
    return {re.sub(r"[.,]", "", n) for n in NUMBER.findall(text)}


def _weather_days(facts: list[dict], today: date | None) -> dict[date, set[str]]:
    """Each forecast day with the numbers that belong to it."""
    days: dict[date, set[str]] = {}
    year = (today or date.today()).year
    for fact in facts:
        forecast = fact.get("days")
        if not isinstance(forecast, list):
            continue  # Itinerary facts use "days" for the number of days.
        for day in forecast:
            found = DATE.search(str(day.get("day", "")))
            if not found:
                continue
            try:
                when = date(year, int(found.group(2)), int(found.group(1)))
            except ValueError:
                continue
            days[when] = {str(day.get(k)) for k in ("minC", "maxC", "rainChance") if k in day}
    return days


def _named_days(norm: str, raw: str, days: dict[date, set[str]], today: date | None) -> set[date]:
    named = set()
    for when in days:
        words = WEEKDAY_WORDS[when.weekday()]
        if any(re.search(rf"\b{w}\b", norm) for w in words):
            named.add(when)
        if re.search(rf"\b0?{when.day}/0?{when.month}\b", raw):
            named.add(when)
    if today is not None:
        if re.search(r"\b(ngay mai|mai)\b", norm) and today + timedelta(days=1) in days:
            named.add(today + timedelta(days=1))
        if re.search(r"\bhom nay\b", norm) and today in days:
            named.add(today)
    return named


def verify(
    sentences: list[str],
    facts: list[dict],
    refs: set[str],
    question: str,
    *,
    today: date | None = None,
    extra_grounding: str = "",
    edit_applied: bool = False,
) -> tuple[list[str], Counter[str]]:
    facts_text = json.dumps(facts, ensure_ascii=False)
    grounded_words = (
        set(normalize_text(f"{facts_text} {question} {extra_grounding}").split())
        | ALWAYS_ALLOWED_WORDS
    )
    allowed_numbers = _numbers(facts_text) | _numbers(question)
    availability = [f.get("available") for f in facts if isinstance(f.get("available"), bool)]
    weather_days = _weather_days(facts, today)
    kept: list[str] = []
    dropped: Counter[str] = Counter()
    emoji_used = 0
    for raw in sentences:
        sentence = raw.strip()
        if not sentence:
            continue
        rule = _broken_rule(
            sentence, refs, allowed_numbers, grounded_words, availability, weather_days, today
        )
        if not edit_applied and EDIT_CLAIM.search(normalize_text(sentence)):
            rule = "V9_unapplied_edit"
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


def _names(text: str) -> list[str]:
    """Runs of two or more capitalised words: "Vũng Tàu", "Mũi Nghinh Phong".

    str.isupper, not a character range: [A-ZÀ-Ỹ] also holds lowercase đ, ô, ạ…, so
    "Tripi đây" was read as a name and the sentence dropped (17/11).
    """
    names: list[str] = []
    run: list[re.Match[str]] = []
    for word in WORD.finditer(text):
        joined = run and text[run[-1].end() : word.start()].isspace()
        if word.group()[0].isupper() and (not run or joined):
            run.append(word)
            continue
        if len(run) > 1:
            names.append(text[run[0].start() : run[-1].end()])
        run = [word] if word.group()[0].isupper() else []
    if len(run) > 1:
        names.append(text[run[0].start() : run[-1].end()])
    return names


def _broken_rule(
    sentence: str,
    refs: set[str],
    allowed_numbers: set[str],
    grounded_words: set[str],
    availability: list[bool | None],
    weather_days: dict[date, set[str]],
    today: date | None,
) -> str | None:
    if any(ref not in refs for ref in REF.findall(sentence)):
        return "V1_unknown_ref"
    without_refs = REF.sub(" ", sentence)
    if not _numbers(without_refs) <= allowed_numbers:
        return "V2_ungrounded_number"
    for name in _names(without_refs):
        words = normalize_text(name).split()
        # The first word of a sentence is capitalised anyway: judge the rest of the name.
        if without_refs.lstrip().startswith(name):
            words = words[1:]
        if any(word not in grounded_words for word in words):
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
    if weather_days:
        numbers = _numbers(DATE.sub(" ", without_refs))
        if numbers and re.search(r"\bhom qua\b", norm):
            return "V8_wrong_day"  # Tripi has no past weather
        named = _named_days(norm, without_refs, weather_days, today)
        if numbers and named and not numbers <= set().union(*(weather_days[d] for d in named)):
            return "V8_wrong_day"
    return None
