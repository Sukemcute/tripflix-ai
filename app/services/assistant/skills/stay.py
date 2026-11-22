from datetime import UTC, datetime

import httpx

from app.services.assistant.schemas import Answer, Card, Places, Stays, Understanding


async def search_stays(core: httpx.AsyncClient, understood: Understanding) -> Answer:
    if len(understood.place.strip()) < 2:
        return Answer(kind="clarify", text="Bạn muốn tìm chỗ ở tại đâu?")
    start, end = understood.check_in, understood.check_out
    # Past days are refused by the planner against the turn's own "today".
    if start is None or end is None or end <= start:
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
        }
        | ({"priceMax": cap} if (cap := understood.price_max_per_night) else {}),
    )
    response.raise_for_status()
    # Core filters by priceMax; check again so a card never breaks the user's cap (D01, D03).
    stays = [
        stay
        for stay in Stays.model_validate(response.json()).items
        if cap is None or stay.unitPrice <= cap
    ][:5]
    if not stays:
        if cap:
            return Answer(
                kind="no_result",
                text=f"Chưa có chỗ ở còn phòng dưới {vnd(cap)}/đêm cho ngày bạn chọn. "
                "Bạn muốn nới ngân sách hay đổi ngày không?",
                suggestions=["Nới ngân sách", "Đổi ngày"],
            )
        return Answer(
            kind="no_result", text="Mình chưa tìm thấy chỗ ở còn phòng theo ngày đã chọn."
        )
    return Answer(
        kind="answer",
        text=f"Đây là chỗ ở còn phòng {start:%d/%m}–{end:%d/%m} cho {understood.adults} người"
        + (f", dưới {vnd(cap)}/đêm." if cap else "."),
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


def vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + "đ"
