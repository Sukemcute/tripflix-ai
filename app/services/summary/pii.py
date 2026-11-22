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

# Person names: a full name is basic personal data (Nghị định 13/2023/NĐ-CP, Điều 2). No
# Vietnamese NER is trained on noisy comments (VLSP, PhoNER are news), so names are caught
# like Presidio's pattern recognizers: a context word, then the name.
# 1. A kinship or job word, then 1-3 Capitalized syllables: "bạn Quế", "anh Diệp Trọng Tín",
#    "lễ tân Hà". Vietnamese addresses people by kinship term + given name (Vietnamese pronouns).
# 2. A common surname, then the middle name Thị or Văn: "Nguyễn Văn Đình Tuân". Surnames
#    alone also start places ("Hồ Tràm", "Lý Sơn") and streets ("Trần Hưng Đạo").
# Run on 3,058 hotel reviews and 92,977 YouTube comments, 40 hits read per set: about 85% and
# 92% were names (BAO_CAO). A miss leaks a name; a false hit only hides one word.
# shortcut: lowercase or unaccented names ("anh cuong"), names after "và" or a comma, and
# names with no cue are not caught; add a name list or a model if logs show leaks.
NAME_MASK = "[tên]"
_UP = "A-ZÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸĐ"
_LOW = "a-zàáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ"
_CAP = rf"[{_UP}][{_LOW}]+"
_CUES = (
    "anh|chị|em|cô|chú|bác|ông|bà|bạn|cậu|dì|thím|mợ|bé|sếp|"
    "nhân viên|lễ tân|hướng dẫn viên|hdv|tài xế|quản lý|bảo vệ"
)
# lowercase or Capitalized cue (sentence start); the teencode cues a/c/e only in lowercase
_NAME_AFTER_CUE = re.compile(
    rf"(?<![{_LOW}{_UP}])((?:{_CUES})|(?:{_CUES.title()})|[ace])\s+({_CAP}(?:\s+{_CAP}){{0,2}})"
)
# Places and set phrases that start with a kinship word, and words that follow one but are
# no name: "Bãi Ông Lang", "Cô Tô", "Bà Rịa", "A Di Đà Phật", "nhân viên Hành lý".
_NOT_A_NAME = re.compile(
    r"(?:Lang|Lãng|Tô|Rịa|Nà|Đen|Om|Chiểu|Triệu|Trưng|Chúa|Di Đà|Việt|Tây|Khmer|Hotel|Resort|"
    r"Homestay|Villa|Vinpearl|Lễ|Tân|Hành|Sĩ|Hai|Ba|Tư|Năm|Sáu|Bảy|Tám|Chín|Mười)\b"
)
_SURNAMES = "Nguyễn|Trần|Lê|Phạm|Hoàng|Huỳnh|Phan|Vũ|Võ|Đặng|Bùi|Đỗ|Hồ|Ngô|Dương|Lý"
_FULL_NAME = re.compile(rf"(?<![{_LOW}{_UP}])(?:{_SURNAMES})\s+(?:Thị|Văn)(?:\s+{_CAP}){{1,2}}")
_ADDRESS_BEFORE = re.compile(r"(?:đường|phố|quận|huyện|phường|xã|tp\.?|thành phố|số)\s*$", re.I)


@dataclass(frozen=True)
class PromptComment:
    cid: str  # temporary code sent to the LLM
    text: str  # PII masked
    is_first_hand: bool
    context: tuple[str, ...] = ()  # parent texts of replies, PII masked; not this writer's view


def mask_pii(text: str) -> str:
    for pattern in _PII:
        text = pattern.sub(MASK, text)
    return _mask_names(text)


def _mask_names(text: str) -> str:
    def after_cue(m: re.Match[str]) -> str:
        return m.group(0) if _NOT_A_NAME.match(m.group(2)) else f"{m.group(1)} {NAME_MASK}"

    def full_name(m: re.Match[str]) -> str:
        return m.group(0) if _ADDRESS_BEFORE.search(text[: m.start()]) else NAME_MASK

    text = _FULL_NAME.sub(full_name, text)  # first: "bạn Nguyễn Văn An" -> "bạn [tên]"
    return _NAME_AFTER_CUE.sub(after_cue, text)


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
