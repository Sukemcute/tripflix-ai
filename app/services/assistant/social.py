"""Small talk without a Skill: greet, introduce, steer back to travel, remind on profanity.

Code picks the move from the message and the recent history, and a fixed sentence for it
from a pool, so the reply varies and works with the LLM off. The Responder then rewrites it
in Tripi's voice from the same facts (Vũng Tàu report and Bảo's request, 2026-11-17).
"""

import re
import unicodedata
import zlib
from collections.abc import Sequence
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from app.services.assistant.schemas import Answer, Turn
from app.services.summary.vi_text import normalize_text

LEXICON = Path(__file__).resolve().parents[2] / "lexicons" / "chat" / "abuse.v1.yaml"
GREETING_TEXT = r"^(?:hi+|hell?o+|hey+|alo+|(?:xin )?chao(?: ban| tripi| cau| nha| ne)*)\W*$"
REPEAT_AFTER = 2  # the third greeting (or same line) in a row is steered to travel [HIỆU CHỈNH]
RECENT_USER_TURNS = 6
# A rude message with one of these still asks for something; without them it is only venting.
# "ve", "chuyen" alone fold "về", "chuyện": only as "vé máy bay", "chuyến bay" [HIỆU CHỈNH].
REQUEST_CUE = (
    r"\b(tim|kiem|dat|book|goi y|xep|lich trinh|lo trinh|ks|khach san|homestay|resort|cho o"
    r"|phong|may bay|ve (may bay|xe)|chuyen (bay|di|xe)|thoi tiet|mang gi|reel|video"
    r"|di dau|an gi|choi gi)\b"
)

POOLS: dict[str, list[str]] = {
    "greeting_intro": [
        "Chào bạn, mình là Tripi nè! Mình tìm reel chuyến đi, lên lịch trình, xem chỗ ở, "
        "thời tiết cho bạn. Bạn đang muốn đi đâu chơi?",
        "Hello hello! Tripi đây, trợ lý du lịch của Tripflix. Kể mình nghe bạn muốn đi đâu, "
        "mình lên lịch trình liền nha.",
        "Hi bạn! Mình là Tripi, chuyên săn chỗ đi chơi và xếp lịch trình. Cuối tuần này bạn "
        "tính đi đâu nè?",
    ],
    "greeting": [
        "Chào lại bạn nè! Hôm nay mình giúp gì cho chuyến đi đây?",
        "Hi, Tripi vẫn ở đây nè! Bạn muốn tìm chỗ đi hay lên lịch trình?",
        "Hello! Có chuyến nào bạn đang tính chưa, kể mình nghe với.",
    ],
    "greeting_repeat": [
        "Mình chào nhau mấy lần rồi đó hihi. Giờ mình lên kèo đi chơi luôn ha, bạn thích biển "
        "hay núi?",
        "Tripi nghe rõ rồi nè! Thử nói mình nơi bạn muốn đi, mình xếp lịch trình ngay.",
        "Chào hoài vậy là có hẹn đi chơi rồi đó nha! Bạn muốn đi đâu, mấy ngày?",
    ],
    "repeat": [
        "Câu này bạn nhắn rồi nè. Hay mình đổi gió, bạn kể nơi muốn đi để Tripi gợi ý nha?",
        "Tripi đọc rồi nha. Muốn mình tìm chỗ đi chơi hay xếp lịch trình cho bạn không?",
    ],
    "identity": [
        "Mình là Tripi, trợ lý du lịch của Tripflix. Mình tìm reel, lộ trình, chỗ ở, chuyến "
        "bay, xem thời tiết và gợi ý đồ mang theo cho bạn.",
        "Tripi đây, bạn đồng hành du lịch của Tripflix! Mình xếp lịch trình theo ngày, tìm "
        "chỗ ở, vé máy bay và nhắc bạn mang gì.",
    ],
    "thanks": [
        "Không có gì nha! Cần gì thêm cứ nhắn Tripi.",
        "Có gì đâu nè, chúc bạn đi chơi vui! Cần gì cứ gọi mình.",
        "Hihi, giúp được bạn là Tripi vui rồi.",
    ],
    "ack": [
        "Okie, cần gì thêm cứ nhắn Tripi nha!",
        "Oke nè, mình ở đây khi bạn cần.",
        "Chốt vậy nha! Muốn chỉnh gì cứ nói mình.",
    ],
    "goodbye": [
        "Hẹn gặp lại nha, chúc bạn có chuyến đi thật vui!",
        "Bye bạn nè, đi chơi vui vẻ và nhớ chụp thật nhiều ảnh nha!",
        "Tạm biệt nha, khi nào muốn đi đâu cứ quay lại tìm Tripi.",
    ],
    "off_topic": [
        "Vụ này Tripi không rành lắm hihi. Nhưng nếu đang cần đổi gió thì mình tìm chỗ đi "
        "chơi cho bạn liền nha!",
        "Nghe cũng vui á! Mà nói chuyện đi chơi là nghề của Tripi, bạn có định đi đâu sắp tới "
        "không?",
        "Cái này mình chịu thua rồi. Hay để Tripi gợi ý một chuyến đi xả stress cho bạn nha?",
    ],
    "abuse": [
        "Mình nói chuyện nhẹ nhàng với nhau thôi nha bạn. Tripi vẫn ở đây giúp bạn lên "
        "chuyến đi nè.",
        "Bình tĩnh nha bạn, có gì chưa ổn cứ nói Tripi sửa. Mình quay lại chuyến đi của bạn nhé?",
        "Tripi hiểu bạn đang bực, mình nói nhẹ nhàng thôi nha. Bạn muốn mình làm lại phần nào?",
    ],
    "ask_why": [
        "Lúc nãy Tripi chưa làm được vì chưa đủ thông tin hoặc dữ liệu cho yêu cầu đó. Bạn "
        "nói rõ hơn giúp mình (nơi đến, mấy ngày) là mình làm lại liền nha.",
    ],
}
REMINDERS = [
    "Mình nói chuyện nhẹ nhàng thôi nha 😊",
    "Bình tĩnh nha bạn, Tripi giúp liền đây.",
]
SOCIAL_MOVES = {"greeting", "identity", "thanks", "ack", "goodbye", "small_talk", "off_topic"}


@cache
def _abuse_patterns() -> tuple[re.Pattern[str], re.Pattern[str]]:
    data: Any = yaml.safe_load(LEXICON.read_text(encoding="utf-8"))
    folded = re.compile("|".join(data["folded"]["patterns"]))
    accented = re.compile("|".join(data["accented"]["patterns"]))
    return folded, accented


def _accented(text: str) -> str:
    return unicodedata.normalize("NFC", text).lower()


def has_abuse(message: str) -> bool:
    """Profanity or an insult in the message; a miss only skips the reminder."""
    folded, accented = _abuse_patterns()
    return bool(folded.search(normalize_text(message)) or accented.search(_accented(message)))


def _recent_user_texts(history: Sequence[Turn]) -> list[str]:
    users = [normalize_text(t.text) for t in history if t.role == "user"]
    return users[-RECENT_USER_TURNS:]


def asks_for_travel(message: str, place: str = "") -> bool:
    """Whether a rude message still asks for something ("đm tìm ks vũng tàu đi")."""
    text = normalize_text(message)
    return bool(re.search(REQUEST_CUE, text) or (place and normalize_text(place) in text))


def choose_move(
    intent: str, message: str, history: Sequence[Turn], *, place: str = ""
) -> str | None:
    """The kind of small-talk reply this turn needs, or None when it is a travel turn."""
    if intent == "ask_why":
        return "ask_why"
    text = normalize_text(message)
    is_abusive = has_abuse(message)
    if is_abusive and not asks_for_travel(message, place):
        # "cặc, chatbot như quần" with a Đà Lạt trip was a search 5/6 and showed reels (17/11).
        return "abuse"
    if intent not in SOCIAL_MOVES:
        return None
    if is_abusive:
        return "abuse"
    recent = _recent_user_texts(history)
    if intent == "greeting" or re.match(GREETING_TEXT, text):
        greetings = sum(bool(re.match(GREETING_TEXT, t)) for t in recent)
        if greetings >= REPEAT_AFTER:
            return "greeting_repeat"
        has_talked = any(t.role == "assistant" for t in history)
        return "greeting" if has_talked else "greeting_intro"
    if recent.count(text) >= REPEAT_AFTER:
        return "repeat"
    return "off_topic" if intent == "small_talk" else intent


def pick(move: str, seed: str) -> str:
    """One sentence of the move's pool; the same seed gives the same sentence (testable)."""
    pool = POOLS[move]
    return pool[zlib.crc32(seed.encode("utf-8")) % len(pool)]


def reminder(seed: str) -> str:
    return REMINDERS[zlib.crc32(seed.encode("utf-8")) % len(REMINDERS)]


def chips(place: str) -> list[str]:
    if place:
        return [f"Lịch trình {place}", f"Thời tiết {place}", "Tìm chỗ ở"]
    return ["Gợi ý đi biển", "Cuối tuần đi đâu?", "Lên lịch trình Đà Lạt"]


def social_answer(move: str, *, place: str, seed: str, history: Sequence[Turn]) -> Answer:
    """A short reply in Tripi's voice; facts let the Responder rewrite it, never invent."""
    text = pick(move, seed)
    facts: dict[str, Any] = {
        "type": "social",
        "move": move,
        "assistant": "Tripi",
        "app": "Tripflix",
        "place": place or None,
        "fallback": text,
    }
    if move == "greeting_repeat":
        # Grounds "mình chào nhau 3 lần rồi" for the Verifier's number rule.
        said = _recent_user_texts(history)
        facts["timesGreeted"] = 1 + sum(bool(re.match(GREETING_TEXT, t)) for t in said)
    if move == "ask_why":
        last = next((t.text for t in reversed(history) if t.role == "assistant"), "")
        facts["type"], facts["previousReply"] = "previous_reply", last[:300]
    steer = move not in {"thanks", "ack", "goodbye", "identity"}
    return Answer(
        kind="answer", text=text, facts=[facts], suggestions=chips(place) if steer else []
    )
