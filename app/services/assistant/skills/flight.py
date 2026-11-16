from datetime import UTC, datetime, timedelta, timezone

import httpx

from app.services.assistant.schemas import Answer, Card, Flights, Understanding


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
