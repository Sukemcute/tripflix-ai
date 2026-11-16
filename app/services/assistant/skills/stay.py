from datetime import UTC, datetime, timedelta, timezone

import httpx

from app.services.assistant.schemas import Answer, Card, Places, Stays, Understanding


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
