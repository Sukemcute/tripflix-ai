"""From the Controller's plan to an Answer, in code (TF31 v3.1).

The Controller only names intent and slots. Which Core and weather calls run, with which ids
and dates, is decided here; a failing Skill degrades its part of the turn and is never
reported as "sold out" or "nothing found" (DeepResearch_Tripi_2_agent_SWE §4.4). v3.1 adds
the trip memory, social turns that call no Skill, and the fixes of the Expo Web report.
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Coroutine
from datetime import date
from uuid import UUID

import httpx
from pydantic import ValidationError

from app.clients.places import CorePlaces, PlacesClient
from app.clients.weather import WeatherClient
from app.services.assistant import planner, social
from app.services.assistant.controller import is_harmless_off_topic, is_unsafe, off_topic_kind
from app.services.assistant.schemas import (
    Answer,
    Awaiting,
    CardRef,
    ChatRequest,
    TripContext,
    Understanding,
)
from app.services.assistant.skills import trip as trip_skill
from app.services.assistant.skills import weather as weather_skill
from app.services.assistant.skills.content import search
from app.services.assistant.skills.flight import draft_flights, search_flights
from app.services.assistant.skills.plan import TripPlanner
from app.services.assistant.skills.stay import search_stays
from app.services.summary.pii import mask_pii
from app.services.summary.vi_text import normalize_text

logger = logging.getLogger(__name__)
SKILL_SECONDS = 3.0
# Weather is two calls in a row (place, then forecast); a cold TLS start took ~1 s each
# (live run 2026-11-16).
# plan: points, forecast and maybe the hotel; 3 s timed out on staging (Vũng Tàu report P2).
SKILL_SECONDS_BY_NAME = {"weather": 6.0, "plan": 7.0}
SKILL_ERRORS = (TimeoutError, httpx.HTTPError, ValidationError, KeyError, ValueError, TypeError)
LABELS = {
    "content": "kết quả tìm kiếm",
    "stay": "phòng",
    "flight": "chuyến bay",
    "trip": "reel",
    "weather": "thời tiết",
    "plan": "lộ trình",
}
# Stage B (plan B7): the whole trip and its edits, run by TripPlanner.
PLAN_INTENTS = {
    "plan_trip",
    "change_stay",
    "change_transport",
    "remove_stop",
    "move_stop",
    "undo",
    "select_option",
    "confirm_booking",
}
REEL_KINDS = {"video", "plan", "post"}
DISCOVERY_SUGGESTIONS = ["Thời tiết ở đó", "Cần mang gì?", "Tìm chỗ ở"]
NEEDS_REEL = Answer(
    kind="no_result",
    text="Bạn mở Tripi từ một reel, hoặc chọn một reel Tripi vừa gợi ý, để mình đọc lộ trình, "
    "review và khách sạn của reel đó nha.",
)
# Requests a clarifying question can be about; the answer to it finishes them (v2.1).
AWAITABLE = {
    "search",
    "find_stay",
    "find_flight",
    "plan_trip",
    "weather",
    "packing",
    "find_reel",
    "change_transport",
}
# Turns answered without a Skill; their replies live in social.py (varied pools).
SOCIAL = {"greeting", "identity", "thanks", "ack", "goodbye", "small_talk", "off_topic", "ask_why"}


class Turn:
    def __init__(
        self,
        request: ChatRequest,
        parsed: Understanding | None,
        *,
        core: httpx.AsyncClient,
        weather: WeatherClient,
        today: date,
        places: PlacesClient | None = None,
        disabled_skills: frozenset[str] = frozenset(),
    ) -> None:
        self.request = request
        self.parsed = parsed
        self.core = core
        self.weather = weather
        self.today = today
        self.disabled_skills = disabled_skills
        self.degraded: list[str] = []
        self.is_asked = planner.has_asked_before(request)
        self.memory = request.trip or TripContext()
        place = normalize_text(self.memory.place)
        is_chat = request.search_mode != "reel"
        self.cancel_destination = bool(
            is_chat
            and place
            and re.fullmatch(
                rf"(?:toi |minh |em )?khong (?:con )?muon di {re.escape(place)} nua",
                normalize_text(request.message),
            )
        )
        self.short_stay_dates = planner.short_stay_dates(request, today) if is_chat else None
        self.reel_id: UUID | None = None
        self.is_reel_from_cards = False
        self.places = places or CorePlaces(core)
        self.planned_trip: TripContext | None = None

    async def answer(self) -> Answer:
        answer = await self._answer()
        parsed = self.parsed
        if (
            answer.kind == "no_result"
            and not answer.cards
            and (
                parsed is None
                or parsed.intent in {"search", "find_reel", "find_stay", "find_flight"}
            )
        ):
            intent = parsed.intent if parsed else "search"
            kind = {"find_stay": "stay", "find_flight": "flight", "find_reel": "content"}.get(
                intent, "content" if self.request.search_mode == "reel" else "search"
            )
            place = (parsed.place if parsed else "") or self.memory.place
            subject = place or (parsed.query if parsed else "") or "chuyến đi của bạn"
            if parsed and kind == "flight":
                origin = parsed.from_city or parsed.from_airport or self.memory.origin_city
                destination = parsed.to_city or parsed.to_airport or place
                subject = f"{origin} → {destination}" if origin and destination else subject
            if parsed:
                start = parsed.flight_date if kind == "flight" else parsed.check_in
                if start:
                    subject += f" ngày {start:%d/%m}"
                if kind == "stay" and parsed.check_out:
                    subject += f" đến {parsed.check_out:%d/%m}"
            answer = social.no_result_answer(
                answer,
                kind=kind,
                subject=subject,
                place=place,
                seed=self._seed(),
                history=self.request.history,
            )
        move = parsed and social.choose_move(
            parsed.intent,
            self.request.message,
            self.request.history,
            said_rude=parsed.is_rude,
            has_request=social.names_its_target(self.request.message, parsed),
        )
        rude = parsed is not None and social.is_rude(self.request.message, said_rude=parsed.is_rude)
        if (
            not move
            and rude
            and answer.kind != "refusal"
            and not social.is_off_topic_answer(answer)
        ):
            # Rude but asking for something real: help, with one light reminder first.
            note = social.reminder(self._seed())
            answer.text = f"{note} {answer.text}"
            answer.lead = f"{note} {answer.lead}" if answer.lead else None
        return answer

    def _seed(self) -> str:
        return f"{self.request.conversation_id}:{len(self.request.history)}"

    async def _answer(self) -> Answer:
        if self.request.action is not None:  # a button: no LLM was called
            return await self._plan_step(None)
        if is_unsafe(self.request.message):
            return social.refusal_answer(seed=self._seed(), history=self.request.history)
        if self.cancel_destination:
            return Answer(kind="clarify", text="Được nha. Bạn muốn đổi sang điểm đến nào?")
        if isinstance(self.short_stay_dates, planner.DateProblem):
            return Answer(kind="clarify", text=self.short_stay_dates.question)
        parsed = self.parsed
        if self.short_stay_dates is not None:
            if parsed is None or parsed.intent not in {"find_stay", "check_room"}:
                parsed = Understanding(
                    intent="find_stay",
                    place=self.memory.place,
                    adults=self.memory.adults,
                    price_max_per_night=self.memory.price_max_per_night,
                    children=self.memory.children,
                    infants=self.memory.infants,
                )
                self.parsed = parsed
            # A date-only reply is for the stay that Tripi just asked about.
            parsed.place = self.memory.place or parsed.place
            parsed.check_in, parsed.check_out = self.short_stay_dates
            parsed.day_ref, parsed.nights, parsed.is_past = "none", None, False
        outside = off_topic_kind(self.request.message)
        if (
            parsed
            and parsed.intent in {"refusal", "off_topic"}
            and is_harmless_off_topic(self.request.message, parsed)
            and (outside or not social.is_rude(self.request.message, said_rude=parsed.is_rude))
            and not re.match(social.GREETING_TEXT, normalize_text(self.request.message))
        ):
            return social.off_topic_answer(
                outside or "other",
                place=self.memory.place,
                seed=self._seed(),
                history=self.request.history,
            )
        if parsed and parsed.intent == "refusal":
            return social.refusal_answer(seed=self._seed(), history=self.request.history)
        if parsed is None or self.request.search_mode == "reel":
            return await self._discover()
        fixed = self._fixed(parsed)
        if fixed is not None:
            return fixed
        intent = parsed.intent
        if intent in PLAN_INTENTS:
            return await self._plan_step(parsed)
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
        if self.cancel_destination:
            return TripContext()
        if isinstance(self.short_stay_dates, planner.DateProblem):
            return self.memory
        # A Stage B step already wrote the plan it changed.
        memory = (self.planned_trip or self.memory).model_copy(deep=True)
        parsed = self.parsed
        if parsed is not None and parsed.intent not in SOCIAL:
            if parsed.place and parsed.place != memory.place:
                memory.place, memory.date_from, memory.date_to = parsed.place, None, None
                # The plan belonged to the old place.
                memory.stay, memory.transport, memory.days = None, None, []
                memory.return_transport = None
                memory.pending, memory.ops = [], []
                memory.pending_flights = []
            start = planner.start_day(parsed, self.today)
            if (
                start is not None
                and start >= self.today
                and not (self.planned_trip is not None and parsed.intent == "plan_trip")
            ):
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
        if any(c.kind == "flight" for c in answer.cards):
            memory.pending_flights = draft_flights(answer.cards)
        memory.asked = memory.asked or answer.kind == "clarify"
        # What Tripi just asked for, so a short reply ("Vũng tàu") finishes it next turn.
        memory.awaiting = (
            self.planned_trip.awaiting
            if (answer.kind == "clarify" and self.planned_trip is not None)
            else None
        )
        if (
            memory.awaiting is None
            and answer.kind == "clarify"
            and parsed is not None
            and parsed.intent in AWAITABLE
        ):
            missing = parsed.missing if parsed.missing in {"place", "dates"} else "place"
            memory.awaiting = Awaiting.model_validate(
                {"intent": parsed.intent, "missing": missing, "nights": parsed.nights}
            )
        return memory

    # ---- social turns, refusals and questions: no Skill

    def _fixed(self, parsed: Understanding) -> Answer | None:
        move = social.choose_move(
            parsed.intent,
            self.request.message,
            self.request.history,
            said_rude=parsed.is_rude,
            has_request=social.names_its_target(self.request.message, parsed),
        )
        if move:
            return social.social_answer(
                move, place=self.memory.place, seed=self._seed(), history=self.request.history
            )
        if parsed.intent == "refusal":
            return social.refusal_answer(seed=self._seed(), history=self.request.history)
        if parsed.intent != "clarify":
            return None
        if self.is_asked:  # one question per conversation: go on with what we have
            return None
        place = parsed.place.strip()
        if parsed.missing == "dates":
            destination = f" {place}" if place else ""
            question = f"Bạn dự định đi{destination} vào ngày nào?"
        elif (parsed.to_airport or parsed.to_city) and not (
            parsed.from_airport or parsed.from_city
        ):
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
        return Answer(kind="clarify", text=planner.STAY_DATE_QUESTION)

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
            self.is_reel_from_cards = True
            return _as_uuid(cards[parsed.card_ordinal - 1].id)
        if parsed.reel_query:
            scores = {c.ref: trip_skill.match_score(parsed.reel_query, c.title) for c in cards}
            best = max(scores.values(), default=0.0)
            fits = [c for c in cards if best >= 0.5 and scores[c.ref] == best]
            if len(fits) == 1:
                self.is_reel_from_cards = True
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
            # A name given with the reel in view is checked against it (P15, R14); a reel just
            # picked by that name from the last cards is not checked twice (chain §6.1, turn 3).
            query = "" if self.is_reel_from_cards else parsed.reel_query
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

    # ---- Stage B: plan the whole trip and edit it (plan B6, B7)

    async def _plan_step(self, parsed: Understanding | None) -> Answer:
        trip_planner = TripPlanner(
            core=self.core,
            places=self.places,
            weather=self.weather,
            today=self.today,
            trip=self.memory.model_copy(deep=True),
        )
        trip_planner.trip.awaiting = None
        action = self.request.action
        if action is not None:
            step = {
                "select": lambda: trip_planner.select(ref=action.ref),
                "remove_stop": lambda: trip_planner.remove_stop(stop_id=action.stop_id),
                "undo": trip_planner.undo,
            }[action.type]()
        else:
            assert parsed is not None
            step = {
                "plan_trip": lambda: trip_planner.plan(parsed, message=self.request.message),
                "change_stay": lambda: trip_planner.stay_options(parsed),
                "select_option": lambda: trip_planner.select(
                    ordinal=parsed.card_ordinal, message=self.request.message
                ),
                "remove_stop": lambda: trip_planner.remove_stop(name=parsed.stop_name),
                "move_stop": lambda: trip_planner.move_stop(
                    parsed.stop_name,
                    anchor_name=parsed.anchor_name,
                    placement=parsed.placement,
                    target_day=parsed.target_day,
                    target_slot=parsed.target_slot,
                ),
                "undo": trip_planner.undo,
                "change_transport": lambda: trip_planner.transport(parsed),
                "confirm_booking": trip_planner.confirm,
            }[parsed.intent]()
        answer = await self._run_value("plan", step)
        if answer is None:
            return self._failed("plan")
        self.planned_trip = trip_planner.trip
        before, after = self.memory, trip_planner.trip
        answer.edit_applied = (
            answer.kind == "answer"
            and bool(before.days or action is not None or (parsed and parsed.intent != "plan_trip"))
            and any(
                getattr(before, field) != getattr(after, field)
                for field in ("days", "stay", "transport", "return_transport")
            )
        )
        if (
            parsed is not None
            and parsed.intent == "plan_trip"
            and answer.kind == "no_result"
            and not trip_planner.trip.days
            and trip_planner.trip.place
        ):
            # No points with coordinates there (Hội An, live eval 17/11): show its reels instead
            # of a dead end, and say why there is no day-by-day plan.
            place = trip_planner.trip.place
            found = await self._discover()
            if found.kind == "answer":
                note = f"Tripflix chưa có đủ điểm ở {place} để xếp lịch theo ngày, xem reel nè."
                found.text = f"{note} {found.text}"
                found.lead = f"{note} {found.lead}" if found.lead else note
                return found
        return answer

    # ---- running Skills with their own deadline

    async def _run(self, name: str, call: Awaitable[Answer]) -> Answer:
        answer = await self._run_value(name, call)
        return answer if answer is not None else self._failed(name)

    async def _run_value(self, name: str, call: Awaitable):
        if name in self.disabled_skills:
            if isinstance(call, Coroutine):
                call.close()  # never started: close it so Python does not warn
            if name not in self.degraded:
                self.degraded.append(name)
            return None
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
