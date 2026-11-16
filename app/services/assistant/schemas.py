"""Wire models of POST /chat and the core responses Tripi reads (TF31)."""

import re
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class WireModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


class Turn(WireModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=2000)
    kind: Literal["answer", "clarify", "refusal", "no_result", "fallback"] = "answer"


class ChatRequest(WireModel):
    conversation_id: UUID
    message: str = Field(min_length=1, max_length=500, pattern=r"\S")
    history: list[Turn] = Field(default_factory=list, max_length=10)
    search_mode: Literal["reel"] | None = None
    # The reel the chat was opened from; Skills read it, the LLM never sees the id.
    context_post_id: UUID | None = None


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
    ]
    query: str = Field(default="", max_length=200)
    missing: Literal["place", "dates", "none"] = "none"
    place: str = Field(default="", max_length=100)
    check_in: date | None = None
    check_out: date | None = None
    adults: int = Field(default=2, ge=1, le=99)
    from_airport: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    to_airport: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    flight_date: date | None = None
    cheapest_only: bool = False
    # Relative days are resolved by code in Vietnam time, never computed by the LLM.
    day_ref: Literal[
        "none", "today", "tomorrow", "this_weekend", "next_weekend", "saturday", "sunday"
    ] = "none"
    nights: int | None = Field(default=None, ge=0, le=30)
    # True when the user means the reel the chat was opened from ("video này", "ks đó").
    uses_context_post: bool = False

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
    label: str
    detail: str = ""


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
    # v3 cards without a price: weather days, a packing list, itinerary days.
    lines: list[CardLine] | None = None
    source: str | None = None  # attribution the app must show, e.g. "Open-Meteo.com"


class Answer(WireModel):
    kind: Literal["answer", "clarify", "refusal", "no_result", "fallback"]
    text: str  # fixed template: what the user sees when the Responder is off or fails
    cards: list[Card] = Field(default_factory=list)
    # What the Responder may talk about: short fields only, never prices (Verifier V2).
    facts: list[dict] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


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
    isAvailable: bool
    priceFrom: float | None = Field(ge=0, allow_inf_nan=False)
    fares: list[FlightFare] = Field(default_factory=list)


class Flights(BaseModel):
    flights: list[FlightOffer]
