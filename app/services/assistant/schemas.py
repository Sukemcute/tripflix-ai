"""Wire models of POST /chat and the core responses Tripi reads (TF31)."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
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
    intent: Literal[
        "search", "find_reel", "find_stay", "find_flight", "clarify", "refusal", "small_talk"
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


class Answer(WireModel):
    kind: Literal["answer", "clarify", "refusal", "no_result", "fallback"]
    text: str
    cards: list[Card] = Field(default_factory=list)


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
