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

from app.services.assistant.controller import CALENDAR_DATE, DATE_WORDS
from app.services.assistant.schemas import Answer, Turn, Understanding
from app.services.summary.vi_text import normalize_text

LEXICON = Path(__file__).resolve().parents[2] / "lexicons" / "chat" / "abuse.v1.yaml"
GREETING_TEXT = r"^(?:hi+|hell?o+|hey+|alo+|(?:xin )?chao(?: ban| tripi| cau| nha| ne)*)\W*$"
REPEAT_AFTER = 2  # the third greeting (or same line) in a row is steered to travel [HIỆU CHỈNH]
RECENT_USER_TURNS = 6
# Intents that lead to a Skill and cards. Without a request in the message they run none:
# the trip on screen never turns venting into a search (v8, 2026-11-17).
SKILL_INTENTS = {
    "search", "find_reel", "find_stay", "find_flight", "check_room", "post_itinerary",
    "post_reviews", "weather", "packing", "plan_trip", "change_stay", "change_transport",
    "clarify", "confirm_booking",
}  # fmt: skip

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
POOLS.update(
    {
        "refusal": [
            "Tripi không hỗ trợ yêu cầu nguy hiểm hoặc can thiệp quy tắc. "
            "Mình có thể giúp bạn lên chuyến đi an toàn.",
            "Mình không làm theo yêu cầu gây hại hay bỏ qua hướng dẫn. "
            "Bạn có thể hỏi Tripi về một chuyến du lịch an toàn.",
            "Yêu cầu này Tripi không thể hỗ trợ. "
            "Mình sẵn sàng giúp tìm lịch trình, phòng và vé cho chuyến đi an toàn.",
            "Tripi giữ nguyên giới hạn an toàn và không hỗ trợ việc gây hại. "
            "Mình quay lại chuyện du lịch nhé?",
        ],
        "off_topic_math": [
            "Tripi không giải toán hay tính đáp án nha.",
            "Bài toán này nằm ngoài phạm vi của Tripi, mình không làm lời giải đâu nè.",
            "Mình không nhận giải bài tập toán, nghề của Tripi là lo chuyến đi nha.",
            "Tripi xin nhường phần giải toán, mình không phải gia sư đâu nè.",
        ],
        "off_topic_code": [
            "Tripi không viết code hay sửa chương trình nha.",
            "Lập trình nằm ngoài phạm vi của mình, Tripi không làm bài code đâu nè.",
            "Mình không nhận viết hàm hay gỡ lỗi phần mềm nha.",
            "Tripi không làm trợ lý lập trình, mình chỉ chuyên chuyện đi chơi thôi nè.",
        ],
        "off_topic_writing": [
            "Tripi không viết bài văn, làm bài hay dịch văn bản nha.",
            "Viết bài và dịch câu nằm ngoài phạm vi của Tripi, mình không làm phần đó đâu nè.",
            "Mình không nhận làm bài văn hay bài dịch, Tripi chuyên lo chuyến đi nha.",
            "Phần văn và dịch thuật mình xin nhường, Tripi không làm bài hộ đâu nè.",
        ],
        "off_topic_knowledge": [
            "Tripi không trả lời kiến thức chung ngoài du lịch nha.",
            "Câu hỏi kiến thức này ngoài phạm vi của mình, Tripi không giải đáp phần đó đâu nè.",
            "Mình không làm bách khoa toàn thư hay tư vấn tài chính nha.",
            "Phần kiến thức ngoài du lịch mình xin nhường, Tripi không trả lời lĩnh vực đó đâu nè.",
        ],
        "off_topic_other": [
            "Chuyện ngoài du lịch này Tripi không hỗ trợ nha.",
            "Việc này ngoài phạm vi nên Tripi không làm phần đó, mình chỉ giúp chuyện đi chơi nè.",
            "Mình không nhận xử lý yêu cầu ngoài du lịch nha.",
            "Vụ ngoài lề này Tripi xin nhường, mình không làm phần đó đâu nè.",
        ],
        "empty_stay": [
            "Chưa có chỗ ở phù hợp cho {subject}; bạn thử đổi ngày nhận phòng nha?",
            "Tìm chỗ ở cho {subject} chưa ra lựa chọn phù hợp; mình xem nơi lân cận nhé?",
            "Chưa tìm được phòng cho {subject}; bạn muốn nới ngân sách không?",
            "Chỗ ở cho {subject} chưa có kết quả phù hợp; mình bớt điều kiện rồi tìm lại nha?",
        ],
        "empty_flight": [
            "Chưa có vé phù hợp cho {subject}; bạn muốn đổi ngày bay không?",
            "Tìm chuyến cho {subject} chưa có lựa chọn phù hợp; mình thử ngày gần đó nha?",
            "Chưa tìm được vé cho {subject}; bạn muốn bỏ bớt điều kiện giờ bay không?",
            "Chuyến bay cho {subject} chưa có kết quả phù hợp; mình xem sân bay lân cận nhé?",
        ],
        "empty_content": [
            "Chưa thấy reel hay bài phù hợp cho {subject}; bạn thử tên nơi lân cận nha?",
            "Tìm reel và bài về {subject} chưa có kết quả phù hợp; mình thử từ khóa ngắn hơn nhé?",
            "Chưa có reel hay bài khớp {subject}; bạn muốn bỏ bớt điều kiện không?",
            "Mình chưa thấy bài hay reel phù hợp cho {subject}; đổi điểm đến để xem thêm nha?",
        ],
        "empty_search": [
            "Tìm {subject} chưa có kết quả phù hợp; bạn muốn thử nơi lân cận không?",
            "Mình chưa tìm được lựa chọn phù hợp cho {subject}; bớt điều kiện rồi thử lại nha?",
            "Chưa có kết quả khớp {subject}; bạn thử đổi ngày hoặc cách mô tả nhé?",
            "Tìm {subject} chưa ra lựa chọn phù hợp; mình thử một điểm đến khác nha?",
        ],
    }
)
TRAVEL_STEERS = [
    "Hay mình xem tiếp lịch {place} nha?",
    "Mình quay lại chuyến đi {place} nhé?",
    "Bạn muốn Tripi tìm chỗ ở cho chuyến {place} không?",
    "Hay mình xem thời tiết cho chuyến {place} nha?",
]


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


def names_its_target(message: str, parsed: Understanding) -> bool:
    """Whether the message itself names what to act on: a place, a day, a hotel, a reel.

    A rude message is acted on only from its own words, never from the trip in memory
    ("cặc, chatbot như quần" carried Đà Lạt from the chat into a search, 17/11). The model's
    own "is there a request" reading was wrong both ways in the v8 eval, so code checks this.
    """
    text = normalize_text(message)
    named = (parsed.place, parsed.to_city, parsed.from_city, parsed.hotel_name, parsed.reel_query)
    if any(name.strip() and normalize_text(name) in text for name in named):
        return True
    return bool(re.search(DATE_WORDS, text) or re.search(CALENDAR_DATE, message))


def is_rude(message: str, *, said_rude: bool) -> bool:
    """The Controller reads the tone; the word list only backs it up when the model misses."""
    return said_rude or has_abuse(message)


def choose_move(
    intent: str,
    message: str,
    history: Sequence[Turn],
    *,
    said_rude: bool = False,
    has_request: bool = True,
) -> str | None:
    """The kind of small-talk reply this turn needs, or None when it is a request.

    One rule for every place and none: rude without a request gets a reminder, a request is
    answered (Turn adds one reminder when rude), social intents get small talk.
    """
    if intent == "ask_why":
        return "ask_why"
    text = normalize_text(message)
    rude = is_rude(message, said_rude=said_rude)
    if intent in SKILL_INTENTS and rude and not has_request:
        # "cặc, chatbot như quần" during a Đà Lạt chat was a search 5/6 and showed reels (17/11).
        # Only rude turns are held back: a polite question is never blocked on a model mistake.
        return "abuse"
    if intent not in SOCIAL_MOVES:
        return None
    if rude:
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


def was_said(text: str, history: Sequence[Turn]) -> bool:
    recent = [turn.text for turn in history if turn.role == "assistant"][-3:]
    said = {normalize_text(part) for line in recent for part in re.split(r"(?<=[.!?])\s+", line)}
    return any(normalize_text(part) in said for part in re.split(r"(?<=[.!?])\s+", text))


def pick_fresh(pool: list[str], seed: str, history: Sequence[Turn]) -> str:
    start = zlib.crc32(seed.encode("utf-8")) % len(pool)
    ordered = [pool[(start + i) % len(pool)] for i in range(len(pool))]
    return next((text for text in ordered if not was_said(text, history)), ordered[0])


def off_topic_answer(kind: str, *, place: str, seed: str, history: Sequence[Turn]) -> Answer:
    steers = (
        [line.format(place=place) for line in TRAVEL_STEERS]
        if place
        else [
            "Hay mình lên lịch trình một chuyến đi nha?",
            "Bạn muốn Tripi gợi ý chỗ đi chơi không?",
            "Mình quay lại chuyện du lịch nhé?",
            "Hay mình tìm một điểm đến cho cuối tuần nha?",
        ]
    )
    pool = [f"{line} {steer}" for line in POOLS[f"off_topic_{kind}"] for steer in steers]
    text = pick_fresh(pool, seed, history)
    return Answer(
        kind="answer",
        text=text,
        facts=[
            {
                "offTopic": kind,
                "place": place,
                "fallback": text,
            }
        ],
        suggestions=chips(place),
    )


def is_off_topic_answer(answer: Answer) -> bool:
    return any(
        fact.get("offTopic") in {"math", "code", "writing", "knowledge", "other"}
        for fact in answer.facts
    )


def refusal_answer(*, seed: str, history: Sequence[Turn]) -> Answer:
    return Answer(kind="refusal", text=pick_fresh(POOLS["refusal"], seed, history))


def no_result_answer(
    answer: Answer, *, kind: str, subject: str, place: str, seed: str, history: Sequence[Turn]
) -> Answer:
    text = pick_fresh(
        [line.format(subject=subject) for line in POOLS[f"empty_{kind}"]], seed, history
    )
    # Keep specific inventory/price/date reasons, not the generic empty-search sentence.
    keep_reason = kind == "flight" or (
        kind == "stay" and (answer.lead is not None or bool(re.search(r"\d", answer.text)))
    )
    answer.text = f"{answer.text} {text}" if keep_reason else text
    answer.lead = answer.text
    answer.facts = [{"noResult": kind, "place": place, "fallback": text}]
    answer.suggestions = (
        answer.suggestions
        or {
            "stay": ["Đổi ngày", "Nới ngân sách", "Tìm nơi lân cận"],
            "flight": ["Đổi ngày bay", "Bỏ lọc giờ bay", "Tìm tuyến khác"],
            "content": ["Đổi từ khóa", "Tìm nơi lân cận"],
            "search": ["Bớt điều kiện", "Đổi điểm đến"],
        }[kind]
    )
    return answer
