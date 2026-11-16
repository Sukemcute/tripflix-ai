from datetime import UTC, datetime

import httpx

from app.services.assistant.schemas import Answer, Card, FlightOffer, Flights, Understanding


async def search_flights(core: httpx.AsyncClient, understood: Understanding) -> Answer:
    origin, destination = understood.from_airport, understood.to_airport
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
    offers = [
        offer for offer in Flights.model_validate(response.json()).flights if offer.isAvailable
    ]
    # Filter by time before taking the first five: the 17:30 flight was cut off and Tripi
    # said there was none after 15:00 (Expo Web report I08, I09).
    window = _window_text(understood)
    offers = _unique([o for o in offers if _in_window(o.departTime, understood)])
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
                    title=_title(offer),
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
        text=f"Đây là các chuyến còn chỗ{window} ngày {travel_date:%d/%m}.",
        cards=[
            Card(
                ref=f"r{i}",
                id=offer.productId,
                kind="flight",
                title=_title(offer),
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


def _title(offer: FlightOffer) -> str:
    return f"{offer.name} · {offer.departTime}" if offer.departTime else offer.name
