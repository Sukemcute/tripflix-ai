"""From the Controller's plan to an Answer, in code (TF31 v3).

The Controller only names intent and slots. Which Core and weather calls run, in which order,
with which ids, is decided here; a failing Skill degrades its part of the turn and is never
reported as "sold out" or "nothing found" (DeepResearch_Tripi_2_agent_SWE §4.4).
"""

import asyncio
import logging
import re
from collections.abc import Awaitable
from datetime import date

import httpx
from pydantic import ValidationError

from app.clients.weather import WeatherClient
from app.services.assistant import planner
from app.services.assistant.schemas import Answer, ChatRequest, Understanding
from app.services.assistant.skills import trip
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
DISCOVERY_SUGGESTIONS = ["Thời tiết ở đó", "Cần mang gì?", "Tìm chỗ ở"]
NEEDS_REEL = Answer(
    kind="no_result",
    text="Bạn mở Tripi từ một reel để mình đọc lộ trình, review và khách sạn của reel đó nha.",
)


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

    async def answer(self) -> Answer:
        parsed = self.parsed
        if parsed is None or self.request.search_mode == "reel":
            return await self._discover()
        fixed = self._fixed(parsed)
        if fixed is not None:
            return fixed
        intent = parsed.intent
        if intent in {"post_itinerary", "post_reviews", "check_room"}:
            return await self._about_reel(parsed)
        if intent in {"weather", "packing"}:
            return await self._weather_or_packing(parsed)
        if intent == "find_stay":
            return await self._stay(parsed)
        if intent == "find_flight":
            parsed.flight_date = parsed.flight_date or planner.start_day(parsed, self.today)
            if re.search(r"\b(?:rẻ nhất|re nhat|cheapest)\b", self.request.message, re.I):
                parsed.cheapest_only = True
            return await self._run("flight", search_flights(self.core, parsed))
        return await self._discover()

    def _fixed(self, parsed: Understanding) -> Answer | None:
        if parsed.intent == "refusal":
            return Answer(
                kind="refusal", text="Mình hỗ trợ du lịch an toàn. Bạn muốn khám phá nơi nào?"
            )
        if parsed.intent == "small_talk":
            return Answer(
                kind="answer",
                text="Mình là Tripi, trợ lý du lịch của Tripflix. "
                "Mình có thể giúp bạn tìm Reel, lộ trình, khách sạn, chuyến bay, "
                "xem thời tiết và gợi ý đồ mang theo.",
                suggestions=["Đi đâu cuối tuần này?", "Gợi ý reel Đà Lạt"],
            )
        if parsed.intent != "clarify":
            return None
        if self.is_asked:  # one question per conversation: go on with what we have
            return None
        place = parsed.place.strip()
        if parsed.missing == "dates":
            destination = f" {place}" if place else ""
            question = f"Bạn dự định đi{destination} vào ngày nào?"
        elif place:
            question = f"Bạn muốn tìm lộ trình, chỗ ở hay chuyến bay đến {place}?"
        elif parsed.missing == "place":
            question = "Bạn muốn đi đâu?"
        else:
            question = "Bạn muốn mình tìm gì cho chuyến đi này?"
        return Answer(kind="clarify", text=question)

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

    async def _stay(self, parsed: Understanding) -> Answer:
        start, end = planner.stay_dates(parsed, self.today)
        if start is None and self.is_asked:
            # Already asked once: assume this weekend and say so (DeepResearch §5.3).
            parsed.day_ref = "this_weekend"
            start, end = planner.stay_dates(parsed, self.today)
        parsed.check_in, parsed.check_out = start, end
        return await self._run("stay", search_stays(self.core, parsed))

    async def _about_reel(self, parsed: Understanding) -> Answer:
        post_id = self.request.context_post_id
        if post_id is None:
            return NEEDS_REEL
        if parsed.intent == "post_itinerary":
            return await self._run("trip", trip.post_itinerary(self.core, post_id))
        if parsed.intent == "post_reviews":
            return await self._run("trip", trip.post_reviews(self.core, post_id))
        start, end = planner.stay_dates(parsed, self.today)
        if start is None or end is None:
            if not self.is_asked:
                return Answer(kind="clarify", text="Bạn muốn nhận phòng và trả phòng ngày nào?")
            parsed.day_ref = "this_weekend"
            start, end = planner.stay_dates(parsed, self.today)
        if start is None or end is None:  # unreachable: this_weekend always resolves
            return self._failed("stay")
        return await self._run(
            "stay", trip.check_room(self.core, post_id, start, end, parsed.adults)
        )

    async def _weather_or_packing(self, parsed: Understanding) -> Answer:
        place = parsed.place.strip()
        if not place and self.request.context_post_id is not None:
            post = await self._run_value(
                "trip", trip.fetch_post(self.core, self.request.context_post_id)
            )
            if post and post.trip_attachment and post.trip_attachment.destination_name:
                place = post.trip_attachment.destination_name.split(",")[0].strip()
        start, end, is_assumed = planner.trip_days(parsed, self.today)
        weather_answer, days = None, []
        if place:
            result = await self._run_value(
                "weather",
                weather_skill.weather(self.weather, place, start, end, is_assumed=is_assumed),
            )
            if result is not None:
                weather_answer, days = result
        if parsed.intent == "weather":
            if not place:
                return Answer(kind="clarify", text="Bạn muốn xem thời tiết ở đâu?")
            return weather_answer or self._failed("weather")
        nights = parsed.nights if parsed.nights is not None else max(0, (end - start).days - 1)
        return weather_skill.packing(f"{place} {self.request.message}", days, nights)

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
