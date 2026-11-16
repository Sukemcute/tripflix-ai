"""From the Controller's plan to an Answer, in code (TF31 v3.1).

The Controller only names intent and slots. Which Core and weather calls run, with which ids
and dates, is decided here; a failing Skill degrades its part of the turn and is never
reported as "sold out" or "nothing found" (DeepResearch_Tripi_2_agent_SWE §4.4). v3.1 adds
the trip memory, social turns that call no Skill, and the fixes of the Expo Web report.
"""

import asyncio
import logging
import re
from collections.abc import Awaitable
from datetime import date
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.clients.weather import WeatherClient
from app.services.assistant import planner
from app.services.assistant.schemas import (
    Answer,
    CardRef,
    ChatRequest,
    TripContext,
    Understanding,
)
from app.services.assistant.skills import trip as trip_skill
from app.services.assistant.skills import weather as weather_skill
from app.services.assistant.skills.content import search
from app.services.assistant.skills.flight import search_flights
from app.services.assistant.skills.stay import search_stays
from app.services.summary.pii import mask_pii

logger = logging.getLogger(__name__)
SKILL_SECONDS = 3.0
# Weather is two calls in a row (place, then forecast); a cold TLS start took ~1 s each
# (live run 2026-11-16).
SKILL_SECONDS_BY_NAME = {"weather": 6.0}
SKILL_ERRORS = (TimeoutError, httpx.HTTPError, ValidationError, KeyError, ValueError, TypeError)
LABELS = {
    "content": "kết quả tìm kiếm",
    "stay": "phòng",
    "flight": "chuyến bay",
    "trip": "reel",
    "weather": "thời tiết",
}
REEL_KINDS = {"video", "plan", "post"}
DISCOVERY_SUGGESTIONS = ["Thời tiết ở đó", "Cần mang gì?", "Tìm chỗ ở"]
NEEDS_REEL = Answer(
    kind="no_result",
    text="Bạn mở Tripi từ một reel, hoặc chọn một reel Tripi vừa gợi ý, để mình đọc lộ trình, "
    "review và khách sạn của reel đó nha.",
)
SOCIAL = {
    "greeting": "Chào bạn, mình là Tripi nè! Bạn đang muốn đi đâu chơi?",
    "identity": "Mình là Tripi, trợ lý du lịch của Tripflix. Mình tìm reel, lộ trình, chỗ ở, "
    "chuyến bay, xem thời tiết và gợi ý đồ mang theo cho bạn.",
    "thanks": "Không có gì nha! Cần gì thêm cứ nhắn Tripi.",
    "ack": "Okie, cần gì thêm cứ nhắn Tripi nha!",
    "goodbye": "Hẹn gặp lại nha, chúc bạn có chuyến đi thật vui!",
}


class Turn:
    def __init__(
        self,
        request: ChatRequest,
        parsed: Understanding | None,
        *,
        core: httpx.AsyncClient,
        weather: WeatherClient,
        today: date,
    ) -> None:
        self.request = request
        self.parsed = parsed
        self.core = core
        self.weather = weather
        self.today = today
        self.degraded: list[str] = []
        self.is_asked = planner.has_asked_before(request)
        self.memory = request.trip or TripContext()
        self.reel_id: UUID | None = None

    async def answer(self) -> Answer:
        parsed = self.parsed
        if parsed is None or self.request.search_mode == "reel":
            return await self._discover()
        fixed = self._fixed(parsed)
        if fixed is not None:
            return fixed
        intent = parsed.intent
        if intent in {"post_itinerary", "post_reviews"} or (
            intent == "check_room" and not parsed.hotel_name
        ):
            return await self._about_reel(parsed)
        if intent in {"check_room", "find_stay"} and parsed.hotel_name:
            return await self._named_hotel(parsed)
        if intent in {"weather", "packing"}:
            return await self._weather_or_packing(parsed)
        if intent == "find_stay":
            return await self._stay(parsed)
        if intent == "find_flight":
            return await self._flight(parsed)
        return await self._discover()

    # ---- what Tripi remembers for the next turn

    def next_trip(self, answer: Answer) -> TripContext:
        """The trip memory after this turn: only what the user said or Core confirmed."""
        memory = self.memory.model_copy(deep=True)
        parsed = self.parsed
        if parsed is not None and parsed.intent not in SOCIAL:
            if parsed.place and parsed.place != memory.place:
                memory.place, memory.date_from, memory.date_to = parsed.place, None, None
            start = planner.start_day(parsed, self.today)
            if start is not None and start >= self.today:
                window = planner.day_window(parsed, self.today)
                memory.date_from = window.start
                memory.date_to = window.end if window.end > window.start else None
            memory.adults, memory.children, memory.infants = (
                parsed.adults,
                parsed.children,
                parsed.infants,
            )
            memory.price_max_per_night = parsed.price_max_per_night
        if self.reel_id is not None:
            memory.reel_id = self.reel_id
        elif self.request.context_post_id is not None:
            memory.reel_id = self.request.context_post_id
        shown = [
            CardRef(ref=c.ref, kind=c.kind, id=c.id, title=c.title[:200])
            for c in answer.cards
            if c.kind in REEL_KINDS | {"stay", "flight"}
        ][:5]
        if shown:
            memory.last_cards = shown
        memory.asked = memory.asked or answer.kind == "clarify"
        return memory

    # ---- social turns, refusals and questions: no Skill

    def _fixed(self, parsed: Understanding) -> Answer | None:
        if parsed.intent in SOCIAL or parsed.intent == "small_talk":
            place = self.memory.place
            chips = (
                [f"Thời tiết {place}", "Cần mang gì?"]
                if place and parsed.intent in {"greeting", "ack"}
                else []
            )
            return Answer(
                kind="answer", text=SOCIAL.get(parsed.intent, SOCIAL["identity"]), suggestions=chips
            )
        if parsed.intent == "refusal":
            return Answer(
                kind="refusal", text="Mình hỗ trợ du lịch an toàn. Bạn muốn khám phá nơi nào?"
            )
        if parsed.intent != "clarify":
            return None
        if self.is_asked:  # one question per conversation: go on with what we have
            return None
        place = parsed.place.strip()
        if parsed.missing == "dates":
            destination = f" {place}" if place else ""
            question = f"Bạn dự định đi{destination} vào ngày nào?"
        elif parsed.to_airport and not parsed.from_airport:
            question = "Bạn bay từ thành phố nào đi?"
        elif place:
            question = f"Bạn muốn tìm lộ trình, chỗ ở hay chuyến bay đến {place}?"
        elif parsed.missing == "place":
            question = "Bạn muốn đi đâu?"
        else:
            question = "Bạn muốn mình tìm gì cho chuyến đi này?"
        return Answer(kind="clarify", text=question)

    # ---- discovery, stays, flights

    async def _discover(self) -> Answer:
        parsed = self.parsed
        message = self.request.message.strip()
        if self.request.search_mode == "reel":
            answer = await self._run(
                "content",
                search(self.core, mask_pii(message), reels_only=True, fallback=parsed is None),
            )
        else:
            query = parsed.query if parsed and parsed.query else mask_pii(message)
            reel_request = re.match(
                r"^(?:(?:tìm|tim|cho mình xem)\s+)?(?:reels?|video)\b\s*", message, re.IGNORECASE
            )
            if reel_request and parsed is None:
                query = mask_pii(message[reel_request.end() :])
            answer = await self._run(
                "content",
                search(
                    self.core,
                    query,
                    fallback=parsed is None,
                    reels_only=bool(reel_request or (parsed and parsed.intent == "find_reel")),
                ),
            )
        if answer.kind in {"answer", "fallback"} and answer.cards:
            answer.suggestions = answer.suggestions or DISCOVERY_SUGGESTIONS
        return answer

    def _dates_or_question(self, parsed: Understanding) -> tuple[date, date] | Answer:
        found = planner.stay_range(parsed, self.today)
        if isinstance(found, planner.DateProblem):
            return Answer(kind="clarify", text=found.question)
        if found is None and self.is_asked:
            # Already asked once: assume this weekend and say so (DeepResearch §5.3).
            parsed.day_ref, parsed.nights = "this_weekend", 1
            found = planner.stay_range(parsed, self.today)
        if isinstance(found, tuple):
            return found
        return Answer(kind="clarify", text="Bạn muốn nhận phòng và trả phòng vào ngày nào?")

    async def _stay(self, parsed: Understanding) -> Answer:
        is_one_night_assumed = parsed.check_out is None and not parsed.nights
        dates = self._dates_or_question(parsed)
        if isinstance(dates, Answer):
            return dates
        parsed.check_in, parsed.check_out = dates
        answer = await self._run("stay", search_stays(self.core, parsed))
        if is_one_night_assumed and answer.kind in {"answer", "no_result"}:
            start, end = dates
            answer.lead = f"Tripi tạm tính 1 đêm, nhận {start:%d/%m} trả {end:%d/%m}."
            answer.text = f"{answer.lead} {answer.text}"
        return answer

    async def _named_hotel(self, parsed: Understanding) -> Answer:
        dates = self._dates_or_question(parsed)
        if isinstance(dates, Answer):
            return dates
        start, end = dates
        return await self._run(
            "stay",
            trip_skill.named_hotel_room(self.core, parsed.hotel_name, start, end, parsed.adults),
        )

    async def _flight(self, parsed: Understanding) -> Answer:
        if parsed.round_trip:
            return Answer(
                kind="clarify",
                text="Tripi mới tìm được vé một chiều. Vé khứ hồi bạn chọn ngay ở màn đặt vé, "
                "hoặc hỏi Tripi từng chiều một nha.",
            )
        start = planner.start_day(parsed, self.today)
        if start is not None and start < self.today:
            return Answer(kind="clarify", text=f"Ngày {start:%d/%m} đã qua, bạn bay ngày nào?")
        parsed.flight_date = start
        if re.search(r"\b(?:rẻ nhất|re nhat|cheapest)\b", self.request.message, re.I):
            parsed.cheapest_only = True
        return await self._run("flight", search_flights(self.core, parsed))

    # ---- the reel in view or picked from the last cards

    def _pick_reel(self, parsed: Understanding) -> UUID | str | None:
        """The reel the user means; a question when two cards fit; None when unknown."""
        cards = [c for c in self.memory.last_cards if c.kind in REEL_KINDS]
        if parsed.card_ordinal and len(cards) >= parsed.card_ordinal:
            return _as_uuid(cards[parsed.card_ordinal - 1].id)
        if parsed.reel_query:
            fits = [c for c in cards if trip_skill.matches(parsed.reel_query, c.title)]
            if len(fits) == 1:
                return _as_uuid(fits[0].id)
            if len(fits) > 1:
                names = " hay ".join(f"«{c.title[:50]}»" for c in fits[:3])
                return f"Bạn muốn xem reel nào: {names}?"
        return self.request.context_post_id or self.memory.reel_id

    async def _about_reel(self, parsed: Understanding) -> Answer:
        picked = self._pick_reel(parsed)
        if isinstance(picked, str):
            return Answer(kind="clarify", text=picked)
        if picked is None:
            return NEEDS_REEL
        self.reel_id = picked
        if parsed.intent == "post_reviews":
            return await self._run("trip", trip_skill.post_reviews(self.core, picked))
        if parsed.intent == "post_itinerary":
            # A name given with the reel in view is checked against it (P15, R14).
            query = "" if parsed.card_ordinal else parsed.reel_query
            return await self._run(
                "trip",
                trip_skill.post_itinerary(
                    self.core,
                    picked,
                    day=parsed.itinerary_day,
                    asks_days_count=parsed.asks_days_count,
                    reel_query=query,
                ),
            )
        dates = self._dates_or_question(parsed)
        if isinstance(dates, Answer):
            return dates
        start, end = dates
        return await self._run(
            "stay", trip_skill.reel_room(self.core, picked, start, end, parsed.adults)
        )

    # ---- weather and packing share one forecast for the same days

    async def _weather_or_packing(self, parsed: Understanding) -> Answer:
        place = parsed.place.strip() or self.memory.place
        reel = self.request.context_post_id or self.memory.reel_id
        if not place and reel is not None:
            post = await self._run_value("trip", trip_skill.fetch_post(self.core, reel))
            if post and post.trip_attachment and post.trip_attachment.destination_name:
                place = post.trip_attachment.destination_name.split(",")[0].strip()
        window = planner.day_window(parsed, self.today)
        found = weather_skill.Forecast("no_place")
        if place:
            result = await self._run_value(
                "weather", weather_skill.forecast(self.weather, place, window)
            )
            found = result if result is not None else weather_skill.Forecast("failed")
        if parsed.intent == "weather":
            if not place:
                return Answer(kind="clarify", text="Bạn muốn xem thời tiết ở đâu?")
            if found.status == "failed":
                return self._failed("weather")
            return weather_skill.weather_answer(found, place, window)
        nights = (
            parsed.nights if parsed.nights is not None else max(0, (window.end - window.start).days)
        )
        return weather_skill.packing(parsed, place, found, nights)

    # ---- running Skills with their own deadline

    async def _run(self, name: str, call: Awaitable[Answer]) -> Answer:
        answer = await self._run_value(name, call)
        return answer if answer is not None else self._failed(name)

    async def _run_value(self, name: str, call: Awaitable):
        try:
            async with asyncio.timeout(SKILL_SECONDS_BY_NAME.get(name, SKILL_SECONDS)):
                return await call
        except SKILL_ERRORS:
            logger.warning("chat skill %s failed", name, exc_info=True)
            if name not in self.degraded:
                self.degraded.append(name)
            return None

    def _failed(self, name: str) -> Answer:
        label = LABELS.get(name, "dữ liệu")
        # Never "sold out" or "nothing found": we simply could not check.
        return Answer(
            kind="fallback", text=f"Tripi chưa kiểm được {label} lúc này, bạn thử lại sau nha."
        )


def _as_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None
