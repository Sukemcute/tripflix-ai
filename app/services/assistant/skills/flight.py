import asyncio
import logging
from datetime import UTC, date, datetime, timedelta

import httpx

from app.services.assistant.schemas import (
    Answer,
    Card,
    CardAction,
    DraftTransport,
    FlightOffer,
    Flights,
    Understanding,
)

logger = logging.getLogger(__name__)


def draft_flights(cards: list[Card]) -> list[DraftTransport]:
    return [
        DraftTransport(
            mode="flight",
            summary=c.title[:160],
            ref=c.ref,
            flight_id=c.id,
            fare_code=c.fare_code,
            flight_date=c.flight_date,
            from_airport=c.from_airport,
            to_airport=c.to_airport,
            passengers=c.passengers,
            depart_time=c.depart_time,
            arrive_time=c.arrive_time,
        )
        for c in cards
        if c.kind == "flight"
    ][:5]


async def find_airport(core: httpx.AsyncClient, city: str) -> list[dict]:
    """Airports Core knows for a city name ("ha noi", "hcm", "Đà Nẵng"); empty when none."""
    response = await core.get("/api/suggest", params={"q": city, "types": "airport"})
    response.raise_for_status()
    return [item for item in response.json().get("items") or [] if item.get("type") == "airport"]


async def _airport_or_answer(
    core: httpx.AsyncClient, code: str | None, city: str, *, airports: list[dict] | None = None
) -> str | Answer:
    """The code the Controller gave, else the single airport Core finds for the city."""
    if code or not city:
        return code or ""
    if airports is None:
        airports = await find_airport(core, city)
    if not airports:
        return Answer(
            kind="no_result",
            text=f"Tripflix chưa có chuyến bay tới hoặc đi từ {city}. "
            "Bạn chọn thành phố có sân bay gần đó nha.",
        )
    if len(airports) > 1:
        names = " hay ".join(f"{a.get('name')} ({a.get('refId')})" for a in airports[:3])
        return Answer(kind="clarify", text=f"Bạn muốn bay {names}?")
    return str(airports[0]["refId"])


async def search_flights(
    core: httpx.AsyncClient,
    understood: Understanding,
    *,
    latest: bool = False,
    daytime: bool = False,
) -> Answer:
    # The LLM guesses codes badly for "bay ra hn"; Core knows each city's airport (T8).
    origins = (
        [{"refId": understood.from_airport}]
        if understood.from_airport
        else await find_airport(core, understood.from_city)
        if understood.from_city
        else []
    )
    destinations = (
        [{"refId": understood.to_airport}]
        if understood.to_airport
        else await find_airport(core, understood.to_city)
        if understood.to_city
        else []
    )
    if origins and destinations and (len(origins) > 1 or len(destinations) > 1):
        try:
            response = await core.get("/api/flights/routes")
            response.raise_for_status()
            routes = {(r["fromAirport"], r["toAirport"]) for r in response.json()}
            # Province mergers can add island airports with no route to the destination.
            pairs = [
                (a, b) for a in origins for b in destinations if (a["refId"], b["refId"]) in routes
            ]
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            logger.warning("chat flight routes degraded", exc_info=True)
        else:
            if not pairs:
                start = understood.from_city or understood.from_airport
                end = understood.to_city or understood.to_airport
                return Answer(kind="no_result", text=f"Tripflix chưa có tuyến bay {start} – {end}.")
            origins = [a for a in origins if any(a == origin for origin, _ in pairs)]
            destinations = [b for b in destinations if any(b == dest for _, dest in pairs)]
    origin = await _airport_or_answer(
        core, understood.from_airport, understood.from_city, airports=origins
    )
    if isinstance(origin, Answer):
        return origin
    destination = await _airport_or_answer(
        core, understood.to_airport, understood.to_city, airports=destinations
    )
    if isinstance(destination, Answer):
        return destination
    if destination and not origin:  # ask only what is missing (Expo Web report I11)
        return Answer(kind="clarify", text="Bạn bay từ thành phố nào đi?")
    if not origin or not destination or origin == destination:
        return Answer(kind="clarify", text="Bạn muốn bay từ sân bay nào đến sân bay nào?")
    travel_date = understood.flight_date
    # Past days are refused by Turn against the turn's own "today".
    if travel_date is None:
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
        }
        | ({"children": understood.children} if understood.children else {})
        | ({"infants": understood.infants} if understood.infants else {}),
    )
    response.raise_for_status()
    all_offers = Flights.model_validate(response.json()).flights
    offers = [offer for offer in all_offers if offer.isAvailable]
    if not all_offers:
        return Answer(
            kind="no_result", text=f"Tripflix chưa có tuyến bay {origin} – {destination}."
        )
    if not offers:
        nearby = await _nearby_dates(core, understood, origin, destination)
        note = (
            " Ngày gần đó còn chỗ: " + ", ".join(f"{day:%d/%m}" for day in nearby) + "."
            if nearby
            else ""
        )
        return Answer(
            kind="no_result",
            text=f"Tuyến {origin} – {destination} hết chỗ ngày {travel_date:%d/%m}.{note}",
            suggestions=[f"Bay ngày {day:%d/%m}" for day in nearby],
        )
    # Filter by time before taking the first five: the 17:30 flight was cut off and Tripi
    # said there was none after 15:00 (Expo Web report I08, I09).
    window = _window_text(understood)
    offers = _unique([o for o in offers if _in_window(o.departTime, understood)])
    if daytime:
        offers = [o for o in offers if o.arriveTime is None or (_minutes(o.arriveTime) or 0) >= 420]
    if latest:
        offers.reverse()
    if not offers:
        return Answer(
            kind="no_result",
            text=f"Mình chưa thấy chuyến còn chỗ{window} ngày {travel_date:%d/%m}.",
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
                    title=flight_title(offer),
                    price_from=fare.pricePerPerson,
                    total_price=total,
                    price_basis="per_ticket",
                    observed_at=datetime.now(UTC),
                    flight_date=travel_date,
                    from_airport=origin,
                    to_airport=destination,
                    passengers=understood.adults,
                    fare_code=fare.code,
                    depart_time=offer.departTime,
                    arrive_time=offer.arriveTime,
                    actions=[CardAction(type="select", label="Chọn chuyến này", ref="r1")],
                )
            ],
        )
    return Answer(
        kind="answer",
        text=f"Đây là các chuyến còn chỗ{window} ngày {travel_date:%d/%m}.",
        cards=[
            Card(
                ref=f"r{i}",
                id=offer.productId,
                kind="flight",
                title=flight_title(offer),
                price_from=offer.priceFrom,
                price_basis="per_ticket" if offer.priceFrom is not None else "unavailable",
                observed_at=datetime.now(UTC),
                flight_date=travel_date,
                from_airport=origin,
                to_airport=destination,
                # The app opens its flight screen with these; without it a party of 2 became 1.
                passengers=understood.adults,
                fare_code=next((f.code for f in offer.fares if f.totalPrice is not None), None),
                depart_time=offer.departTime,
                arrive_time=offer.arriveTime,
                actions=[CardAction(type="select", label="Chọn chuyến này", ref=f"r{i}")],
            )
            for i, offer in enumerate(offers[:5], 1)
        ],
    )


async def _nearby_dates(
    core: httpx.AsyncClient, understood: Understanding, origin: str, destination: str
) -> list[date]:
    assert understood.flight_date is not None
    dates = [understood.flight_date + timedelta(days=n) for n in (-1, 1, -2, 2, -3, 3)]

    async def available(day: date) -> bool:
        response = await core.get(
            "/api/flights",
            params={
                "from": origin,
                "to": destination,
                "date": day.isoformat(),
                "passengers": understood.adults,
            }
            | ({"children": understood.children} if understood.children else {})
            | ({"infants": understood.infants} if understood.infants else {}),
        )
        response.raise_for_status()
        return any(o.isAvailable for o in Flights.model_validate(response.json()).flights)

    results = await asyncio.gather(*(available(day) for day in dates), return_exceptions=True)
    if any(isinstance(result, Exception) for result in results):
        logger.warning("chat flight nearby dates degraded")
    return [day for day, result in zip(dates, results, strict=True) if result is True][:3]


def _minutes(clock: str | None) -> int | None:
    try:
        hour, minute = (clock or "").split(":")[:2]
        return int(hour) * 60 + int(minute)
    except ValueError:
        return None


def _in_window(depart: str | None, understood: Understanding) -> bool:
    after, before = _minutes(understood.depart_after), _minutes(understood.depart_before)
    if after is None and before is None:
        return True
    at = _minutes(depart)
    if at is None:
        return False  # a time filter was asked: an unknown time cannot be shown as matching
    return (after is None or at >= after) and (before is None or at <= before)


def _window_text(understood: Understanding) -> str:
    if understood.depart_after and understood.depart_before:
        return f" từ {understood.depart_after} đến {understood.depart_before}"
    if understood.depart_after:
        return f" sau {understood.depart_after}"
    if understood.depart_before:
        return f" trước {understood.depart_before}"
    return ""


def _unique(offers: list[FlightOffer]) -> list[FlightOffer]:
    """One card per flight: core lists each cabin of a flight as its own offer."""
    best: dict[str, FlightOffer] = {}
    for offer in offers:
        key = offer.flightKey or f"{offer.name}|{offer.departTime}"
        kept = best.get(key)
        if kept is None or (offer.priceFrom or 0) < (kept.priceFrom or 0):
            best[key] = offer
    return sorted(best.values(), key=lambda o: _minutes(o.departTime) or 0)


def flight_title(offer: FlightOffer) -> str:
    if offer.departTime and offer.departTime not in offer.name:
        return f"{offer.name} · {offer.departTime}"
    return offer.name
