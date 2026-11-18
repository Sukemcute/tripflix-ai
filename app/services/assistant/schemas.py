"""Wire models of POST /chat and the core responses Tripi reads (TF31)."""

import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel


class WireModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Turn(WireModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=2000)
    kind: Literal["answer", "clarify", "refusal", "no_result", "fallback"] = "answer"


class CardRef(WireModel):
    """A card shown in the last answer, so "the second video" can be found again."""

    ref: str = Field(max_length=8)
    kind: str = Field(max_length=20)
    id: str = Field(max_length=100)
    title: str = Field(default="", max_length=200)


class DraftStop(WireModel):
    """A stop of the planned itinerary; coordinates kept so edits need no new lookup."""

    id: str = Field(max_length=100)
    name: str = Field(max_length=120)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    slot: Literal["sáng", "trưa", "chiều", "tối"] = "sáng"


class DraftChoice(WireModel):
    """A stay the user picked or may pick: on Tripflix (bookable) or outside (for reference)."""

    ref: str = Field(default="", max_length=4)  # o1, o2… on the comparison card
    source: Literal["tripflix", "external"]
    id: str = Field(max_length=100)
    name: str = Field(max_length=120)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)


class DraftTransport(WireModel):
    mode: Literal["flight", "bus"]
    summary: str = Field(max_length=160)
    ref: str = Field(default="", max_length=4)
    flight_id: str | None = Field(default=None, max_length=100)
    fare_code: str | None = Field(default=None, max_length=40)
    flight_date: date | None = None
    from_airport: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    to_airport: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    passengers: int | None = Field(default=None, ge=1, le=9)
    depart_time: str | None = None
    arrive_time: str | None = None


class DraftOp(WireModel):
    """One edit, kept so "hoàn tác" can undo it; only what is needed to put things back."""

    op: Literal["set_stay", "remove_stop"]
    stay: DraftChoice | None = None  # the stay before set_stay
    stop: DraftStop | None = None  # the stop remove_stop took out
    day: int | None = Field(default=None, ge=0, le=13)
    position: int | None = Field(default=None, ge=0, le=12)


class DraftAction(WireModel):
    """A button the user tapped: run as a draft edit without the LLM (DeepResearch §5.2)."""

    type: Literal["select", "remove_stop", "undo"]
    ref: str = Field(default="", max_length=4)
    stop_id: str = Field(default="", max_length=100)


class Awaiting(WireModel):
    """The request Tripi asked a question about and still has to finish."""

    intent: Literal[
        "search",
        "find_stay",
        "find_flight",
        "plan_trip",
        "weather",
        "packing",
        "find_reel",
        "change_transport",
    ]
    missing: Literal["place", "dates", "origin", "origin_dates"] = "place"
    nights: int | None = Field(default=None, ge=0, le=30)


class TripContext(WireModel):
    """What Tripi remembers of the trip being planned (trip memory, v3 "Trip Draft" lite).

    The app keeps it and sends it back each turn; the server re-checks everything against
    Core before use, so an edited copy only spoils its own answers (DeepResearch §5.1).
    v2 (Stage B) adds the plan itself: origin city, stay, way there, stops per day, the
    options on screen and the last edits. Kept small: the app stores the whole chat in 2 KB.
    """

    v: Literal[1, 2] = 2
    place: str = Field(default="", max_length=100)
    date_from: date | None = None
    date_to: date | None = None
    adults: int = Field(default=2, ge=1, le=9)
    children: int = Field(default=0, ge=0, le=9)
    infants: int = Field(default=0, ge=0, le=9)
    price_max_per_night: int | None = Field(default=None, ge=0)
    reel_id: UUID | None = None
    last_cards: list[CardRef] = Field(default_factory=list, max_length=5)
    # A clarifying question was already asked: works even when the app sends no kind.
    asked: bool = False
    # v2: the trip plan (Stage B). City level only: no coordinates of the user (X5).
    origin_city: str = Field(default="", max_length=60)
    interests: list[str] = Field(default_factory=list, max_length=5)
    stay: DraftChoice | None = None
    transport: DraftTransport | None = None
    return_transport: DraftTransport | None = None
    days: list[list[DraftStop]] = Field(default_factory=list, max_length=7)
    pending: list[DraftChoice] = Field(default_factory=list, max_length=4)
    pending_flights: list[DraftTransport] = Field(default_factory=list, max_length=5)
    ops: list[DraftOp] = Field(default_factory=list, max_length=5)
    # v2.1 (2026-11-17, Vũng Tàu report): what Tripi just asked for, so a short answer
    # ("Vũng tàu") finishes that request; and a plan of food stops only.
    awaiting: Awaiting | None = None
    meals_only: bool = False


class ChatRequest(WireModel):
    conversation_id: UUID
    message: str = Field(min_length=1, max_length=500, pattern=r"\S")
    history: list[Turn] = Field(default_factory=list, max_length=30)
    search_mode: Literal["reel"] | None = None
    # The reel the chat was opened from; Skills read it, the LLM never sees the id.
    context_post_id: UUID | None = None
    trip: TripContext | None = None
    # A button on a card (Chọn, Bỏ, Hoàn tác): code runs it, the LLM is not called.
    action: DraftAction | None = None


class Understanding(WireModel):
    """The Controller's plan for one turn. Code turns it into Skill calls (planner.py)."""

    intent: Literal[
        "search",
        "find_reel",
        "find_stay",
        "find_flight",
        "clarify",
        "refusal",
        "small_talk",
        # v3 (2026-11-16): questions about the reel in view, weather and what to bring
        "post_itinerary",
        "post_reviews",
        "check_room",
        "weather",
        "packing",
        # v3.1 (2026-11-16, Expo Web report): short social turns never call a Skill
        "greeting",
        "identity",
        "thanks",
        "ack",
        "goodbye",
        # Stage B (plan B7): plan the whole trip and edit it
        "plan_trip",
        "change_stay",
        "change_transport",
        "remove_stop",
        "undo",
        "select_option",
        "confirm_booking",
        # v2.1 (2026-11-17): harmless chit-chat outside travel, "why" about the last reply
        "off_topic",
        "ask_why",
    ]
    query: str = Field(default="", max_length=200)
    missing: Literal["place", "dates", "none"] = "none"
    place: str = Field(default="", max_length=100)
    check_in: date | None = None
    check_out: date | None = None
    adults: int = Field(default=2, ge=1, le=99)
    from_airport: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    to_airport: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    # City names as the user wrote them; code finds the airport code (Core /api/suggest).
    from_city: str = Field(default="", max_length=60)
    to_city: str = Field(default="", max_length=60)
    flight_date: date | None = None
    cheapest_only: bool = False
    # Relative days are resolved by code in Vietnam time, never computed by the LLM.
    day_ref: Literal[
        "none",
        "today",
        "tomorrow",
        "this_weekend",
        "next_weekend",
        "saturday",
        "sunday",
        "yesterday",
    ] = "none"
    nights: int | None = Field(default=None, ge=0, le=30)
    # True when the user means the reel the chat was opened from ("video này", "ks đó").
    uses_context_post: bool = False
    # v3.1 constraints the user stated; code applies them, never the LLM.
    children: int = Field(default=0, ge=0, le=9)
    infants: int = Field(default=0, ge=0, le=9)
    round_trip: bool = False
    price_max_per_night: int | None = Field(default=None, ge=0)
    depart_after: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    depart_before: str | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    hotel_name: str = Field(default="", max_length=100)
    card_ordinal: int | None = Field(default=None, ge=1, le=5)
    reel_query: str = Field(default="", max_length=100)
    itinerary_day: int | None = Field(default=None, ge=1, le=30)
    asks_days_count: bool = False
    packing_have: list[str] = Field(default_factory=list, max_length=10)
    packing_only: list[str] = Field(default_factory=list, max_length=5)
    packing_limit: int | None = Field(default=None, ge=1, le=20)
    is_beach_trip: bool | None = None
    # Stage B: what the trip should favour, the stop to drop, how full the days are.
    interests: list[str] = Field(default_factory=list, max_length=5)
    stop_name: str = Field(default="", max_length=120)
    pace: Literal["relaxed", "packed"] | None = None
    # "lộ trình ăn uống", "chỉ quán ăn": food and drink stops only, by meal.
    meals_only: bool = False
    # v8 (2026-11-17): the tone, read by the Controller (the word list only backs it up).
    is_rude: bool = False
    # Set by code when a date the user gave is in the past (no weather history yet).
    is_past: bool = False

    @field_validator("check_in", "check_out", "flight_date", mode="before")
    @classmethod
    def drop_placeholder_dates(cls, value: object) -> object:
        # OpenAI strict mode must fill every field and sometimes writes "0000-01-01" for
        # "no date" (live eval 2026-11-16): treat any year before 2000 as no date.
        if isinstance(value, str) and value[:4].isdigit() and int(value[:4]) < 2000:
            return None
        return value

    @field_validator("from_airport", "to_airport", mode="before")
    @classmethod
    def drop_non_iata(cls, value: object) -> object:
        # "Hanoi" instead of "HAN" must not void the whole plan (live eval 2026-11-16): no code
        # means Tripi asks which airports.
        if isinstance(value, str) and not re.fullmatch(r"[A-Z]{3}", value):
            return None
        return value


class SearchItem(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(min_length=1)
    refId: str = Field(min_length=1)
    kind: Literal["post", "plan", "video", "stay", "food", "cafe", "see"]
    title: str = Field(min_length=1, max_length=500)
    priceFrom: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class Section(BaseModel):
    model_config = ConfigDict(extra="ignore")
    items: list[SearchItem]


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    sections: list[Section]


class CardLine(WireModel):
    service: Literal["flight", "stay"] | None = None
    label: str
    detail: str = ""
    # An option the user can pick with a button (comparison card); sent back as action.ref.
    ref: str | None = None


class CardAction(WireModel):
    type: Literal["select", "book"]
    label: str = Field(min_length=1, max_length=40)
    ref: str | None = Field(default=None, max_length=4)
    path: Literal["/trip-builder"] | None = None
    params: dict[str, str] | None = None

    @model_validator(mode="after")
    def check_target(self) -> "CardAction":
        if self.type == "select":
            if not self.ref or self.path is not None or self.params is not None:
                raise ValueError("select requires only a ref")
        elif self.path is None or self.params is None or self.ref is not None:
            raise ValueError("book requires a path and params")
        return self


class Card(WireModel):
    ref: str
    id: str
    kind: str
    title: str
    price_from: float | None
    price_basis: Literal[
        "indicative_per_night",
        "estimated_per_person",
        "per_night_per_room",
        "per_ticket",
        "unavailable",
    ]
    currency: Literal["VND"] = "VND"
    observed_at: datetime
    check_in: date | None = None
    check_out: date | None = None
    total_price: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    flight_date: date | None = None
    from_airport: str | None = None
    to_airport: str | None = None
    passengers: int | None = None
    fare_code: str | None = None
    depart_time: str | None = None
    arrive_time: str | None = None
    # v3 cards without a price: weather days, a packing list, itinerary days.
    lines: list[CardLine] | None = None
    source: str | None = None  # attribution the app must show, e.g. "Open-Meteo.com"
    actions: list[CardAction] | None = None


class Answer(WireModel):
    kind: Literal["answer", "clarify", "refusal", "no_result", "fallback"]
    text: str  # fixed template: what the user sees when the Responder is off or fails
    cards: list[Card] = Field(default_factory=list)
    # What the Responder may talk about: short fields only, never prices (Verifier V2).
    facts: list[dict] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    # A code-made sentence that answers the question itself ("Ngày 2: ..."). It always goes
    # first, so the answer survives whatever the Verifier drops (Expo Web report V05, V08).
    lead: str | None = None


class Place(BaseModel):
    type: str
    refId: str = Field(min_length=1)


class Places(BaseModel):
    items: list[Place]


class Stay(BaseModel):
    hotelId: str = Field(min_length=1)
    name: str = Field(min_length=1)
    unitPrice: float = Field(ge=0, allow_inf_nan=False)
    totalPrice: float = Field(ge=0, allow_inf_nan=False)


class Stays(BaseModel):
    items: list[Stay]


class FlightFare(BaseModel):
    code: str
    pricePerPerson: float | None = Field(ge=0, allow_inf_nan=False)
    totalPrice: float | None = Field(ge=0, allow_inf_nan=False)


class FlightOffer(BaseModel):
    productId: str = Field(min_length=1)
    name: str = Field(min_length=1)
    flightKey: str | None = None
    departTime: str | None = None  # "HH:MM", Vietnam time (core FlightOfferDto)
    arriveTime: str | None = None
    isAvailable: bool
    priceFrom: float | None = Field(ge=0, allow_inf_nan=False)
    fares: list[FlightFare] = Field(default_factory=list)


class Flights(BaseModel):
    flights: list[FlightOffer]
