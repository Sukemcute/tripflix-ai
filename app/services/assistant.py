"""TF31: bounded discovery workflow. Product claims are rendered from Core cards."""

import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.services.summary.pii import mask_pii


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


async def search_flights(core: httpx.AsyncClient, understood: Understanding) -> Answer:
    origin, destination = understood.from_airport, understood.to_airport
    if not origin or not destination or origin == destination:
        return Answer(kind="clarify", text="Bạn muốn bay từ sân bay nào đến sân bay nào?")
    travel_date = understood.flight_date
    today = datetime.now(timezone(timedelta(hours=7))).date()
    if travel_date is None or travel_date < today:
        return Answer(kind="clarify", text="Bạn muốn bay vào ngày nào?")
    if understood.adults > 9:
        return Answer(
            kind="clarify", text="Bạn có thể chia nhóm thành tối đa 9 người mỗi lượt tìm không?"
        )
    response = await core.get(
        "/api/flights",
        params={
            "from": origin,
            "to": destination,
            "date": travel_date.isoformat(),
            "passengers": understood.adults,
        },
    )
    response.raise_for_status()
    offers = [
        offer for offer in Flights.model_validate(response.json()).flights if offer.isAvailable
    ]
    if not offers:
        return Answer(
            kind="no_result", text="Mình chưa tìm thấy chuyến bay còn chỗ cho yêu cầu này."
        )
    if understood.cheapest_only:
        priced = [
            (fare.totalPrice, offer, fare)
            for offer in offers
            for fare in offer.fares
            if fare.totalPrice is not None
        ]
        if not priced:
            return Answer(kind="no_result", text="Chưa có tổng giá vé để chọn chuyến rẻ nhất.")
        total, offer, fare = min(priced, key=lambda candidate: candidate[0])
        return Answer(
            kind="answer",
            text=f"Đây là chuyến có tổng giá thấp nhất cho {understood.adults} người lớn.",
            cards=[
                Card(
                    ref="r1",
                    id=offer.productId,
                    kind="flight",
                    title=offer.name,
                    price_from=fare.pricePerPerson,
                    total_price=total,
                    price_basis="per_ticket",
                    observed_at=datetime.now(UTC),
                    flight_date=travel_date,
                    from_airport=origin,
                    to_airport=destination,
                    passengers=understood.adults,
                    fare_code=fare.code,
                )
            ],
        )
    return Answer(
        kind="answer",
        text="Đây là các chuyến bay còn chỗ theo ngày và số hành khách đã tìm.",
        cards=[
            Card(
                ref=f"r{i}",
                id=offer.productId,
                kind="flight",
                title=offer.name,
                price_from=offer.priceFrom,
                price_basis="per_ticket" if offer.priceFrom is not None else "unavailable",
                observed_at=datetime.now(UTC),
                flight_date=travel_date,
                from_airport=origin,
                to_airport=destination,
            )
            for i, offer in enumerate(offers[:5], 1)
        ],
    )


async def search_stays(core: httpx.AsyncClient, understood: Understanding) -> Answer:
    if len(understood.place.strip()) < 2:
        return Answer(kind="clarify", text="Bạn muốn tìm chỗ ở tại đâu?")
    start, end = understood.check_in, understood.check_out
    # Vietnam uses UTC+7 year-round; avoid requiring system tzdata on Windows.
    today = datetime.now(timezone(timedelta(hours=7))).date()
    if start is None or end is None or start < today or end <= start:
        return Answer(kind="clarify", text="Bạn muốn nhận phòng và trả phòng vào ngày nào?")
    response = await core.get("/api/suggest", params={"q": understood.place, "types": "place"})
    response.raise_for_status()
    places = [item for item in Places.model_validate(response.json()).items if item.type == "place"]
    if len(places) != 1:
        return Answer(
            kind="clarify", text="Bạn có thể ghi rõ tên thành phố hoặc tỉnh muốn ở không?"
        )
    response = await core.get(
        "/api/stays",
        params={
            "placeId": places[0].refId,
            "checkIn": start.isoformat(),
            "checkOut": end.isoformat(),
            "adults": understood.adults,
            "limit": 5,
        },
    )
    response.raise_for_status()
    stays = Stays.model_validate(response.json()).items[:5]
    if not stays:
        return Answer(
            kind="no_result", text="Mình chưa tìm thấy chỗ ở còn phòng theo ngày đã chọn."
        )
    return Answer(
        kind="answer",
        text="Đây là chỗ ở còn phòng theo ngày và số khách đã tìm.",
        cards=[
            Card(
                ref=f"r{i}",
                id=stay.hotelId,
                kind="stay",
                title=stay.name,
                price_from=stay.unitPrice,
                total_price=stay.totalPrice,
                price_basis="per_night_per_room",
                check_in=start,
                check_out=end,
                observed_at=datetime.now(UTC),
            )
            for i, stay in enumerate(stays, 1)
        ],
    )


MAX_VIDEO_CARDS = 3


def build_cards(payload: SearchResponse) -> list[Card]:
    cards: list[Card] = []
    seen: set[str] = set()
    items = [item for section in payload.sections for item in section.items]
    # Video lên trước (tối đa 3) để khung chat hiện thẻ video; còn chỗ mới thêm bài viết, nơi ở.
    videos = [item for item in items if item.kind == "video"]
    others = [item for item in items if item.kind != "video"]
    for section_items in (videos, others):
        for item in section_items:
            if item.id in seen or item.kind not in {"post", "plan", "video", "stay"}:
                continue
            if (
                item.kind == "video"
                and sum(card.kind == "video" for card in cards) == MAX_VIDEO_CARDS
            ):
                continue
            seen.add(item.id)
            basis = "unavailable"
            price = None
            if item.kind in {"stay", "plan"}:
                basis = "indicative_per_night" if item.kind == "stay" else "estimated_per_person"
                price = item.priceFrom
            cards.append(
                Card(
                    ref=f"r{len(cards) + 1}",
                    id=item.refId,
                    kind=item.kind,
                    title=item.title,
                    price_from=price,
                    price_basis=basis,
                    observed_at=datetime.now(UTC),
                )
            )
            if len(cards) == 5:
                return cards
    return cards


async def search(
    core: httpx.AsyncClient, query: str, *, fallback: bool = False, reels_only: bool = False
) -> Answer:
    # Never silently truncate a query: its last words may contain essential constraints.
    if not query.strip() or len(query) > 200:
        return Answer(
            kind="clarify", text="Bạn có thể viết ngắn lại nơi đến và điều muốn tìm không?"
        )
    if reels_only:
        response = await core.post(
            "/api/search/posts", json={"q": query, "postType": "video", "limit": 5}
        )
    else:
        response = await core.post("/api/search", json={"q": query})
    response.raise_for_status()
    if reels_only:
        section = Section.model_validate(response.json())
        section.items = [item for item in section.items if item.kind == "video"]
        cards = build_cards(SearchResponse(sections=[section]))
    else:
        cards = build_cards(SearchResponse.model_validate(response.json()))
    if not cards:
        return Answer(
            kind="no_result", text="Mình chưa tìm thấy kết quả phù hợp với câu tìm kiếm này."
        )
    videos = sum(card.kind == "video" for card in cards)
    has_stays = any(card.kind == "stay" for card in cards)
    if reels_only:
        text = "Đây là các Reel phù hợp."
    elif videos and not has_stays:
        text = f"Tripi tìm được {videos} video phù hợp. Bấm vào thẻ để xem nhé."
    else:
        text = (
            "Bạn có thể xem các kết quả bên dưới. "
            "Giá phòng là giá tham khảo, cần chọn ngày để kiểm tra lại."
        )
    return Answer(kind="fallback" if fallback else "answer", text=text, cards=cards)


def build_understanding_input(request: ChatRequest) -> str:
    return json.dumps(
        {
            "message": mask_pii(request.message),
            "history": [
                {"role": turn.role, "text": mask_pii(turn.text)} for turn in request.history[-6:]
            ],
        },
        ensure_ascii=False,
    )
