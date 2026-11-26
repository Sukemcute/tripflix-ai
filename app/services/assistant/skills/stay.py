from datetime import UTC, datetime

import httpx

from app.services.assistant.schemas import (
    Answer,
    Card,
    CardRef,
    Places,
    Stays,
    TripContext,
    Understanding,
)

TITLE_CHARS = 80  # same cut as the Responder's card titles
STAY_SORT_PARAM = {"price_asc": "price", "price_desc": "price_desc", "stars_desc": "stars"}
SORT_PHRASE = {
    "price_asc": "xếp từ rẻ đến đắt",
    "price_desc": "xếp từ đắt đến rẻ",
    "stars_desc": "sao cao trước",
}


def refine_stay_filters(
    understood: Understanding, shown: list[CardRef], *, remembered: TripContext
) -> Understanding:
    """Turn "đắt hơn" / "rẻ hơn" into a price bound taken from the cards on screen."""
    refined = understood.model_copy()
    prices = [c.price for c in shown if c.kind == "stay" and c.price is not None]
    relative = refined.price_relative
    if relative == "higher":
        if prices:
            refined.price_min_per_night = max(prices) + 1
            # A cap equal to the remembered one came from memory, not from this message.
            cap = refined.price_max_per_night
            if cap and (cap == remembered.price_max_per_night or cap <= max(prices) + 1):
                refined.price_max_per_night = None
        if refined.stay_sort == "none":
            refined.stay_sort = "price_asc" if prices else "price_desc"
    elif relative == "lower":
        if prices:
            refined.price_max_per_night = min(prices) - 1
            floor = refined.price_min_per_night
            if floor and (floor == remembered.price_min_per_night or floor >= min(prices) - 1):
                refined.price_min_per_night = None
        if refined.stay_sort == "none":
            refined.stay_sort = "price_desc" if prices else "price_asc"
    low, high = refined.price_min_per_night, refined.price_max_per_night
    if low and high and low > high:
        refined.price_max_per_night = None
    return refined


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
        | ({"priceMax": cap} if (cap := understood.price_max_per_night) else {})
        | ({"priceMin": floor} if (floor := understood.price_min_per_night) else {})
        | ({"minStars": stars} if (stars := understood.min_stars) else {})
        | (
            {"sort": STAY_SORT_PARAM[understood.stay_sort]}
            if understood.stay_sort in STAY_SORT_PARAM
            else {}
        ),
    )
    response.raise_for_status()
    # Core filters too; check again so a card never breaks what the user asked (D01, D03).
    stays = [
        stay
        for stay in Stays.model_validate(response.json()).items
        if (cap is None or stay.unitPrice <= cap)
        and (floor is None or stay.unitPrice >= floor)
        and (stars is None or stay.stars is None or stay.stars >= stars)
    ][:5]
    if not stays:
        if understood.price_relative in {"higher", "lower"}:
            is_higher = understood.price_relative == "higher"
            bound = understood.price_min_per_night if is_higher else understood.price_max_per_night
            amount = f" {vnd(bound + (-1 if is_higher else 1))}/đêm" if bound else ""
            return Answer(
                kind="no_result",
                text=f"Ngày đó chưa có chỗ nào còn phòng {'đắt' if is_higher else 'rẻ'} hơn"
                f"{amount or ' các căn vừa rồi'}, "
                f"đây đã là nhóm {'cao' if is_higher else 'thấp'} nhất Tripi thấy.",
                suggestions=["Xem căn rẻ hơn" if is_higher else "Xem căn đắt hơn", "Đổi ngày"],
            )
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
        + "".join(
            f", {phrase}"
            for phrase in (
                f"dưới {vnd(cap)}/đêm" if cap else "",
                f"trên {vnd(floor)}/đêm" if floor else "",
                f"từ {stars} sao" if stars else "",
                SORT_PHRASE.get(understood.stay_sort, ""),
            )
            if phrase
        )
        + ".",
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
        facts=[
            {
                "ref": f"r{i}",
                "kind": "stay",
                "title": stay.name[:TITLE_CHARS],
                "pricePerNight": int(stay.unitPrice),
                "priceText": vnd(int(stay.unitPrice)),
                "stars": stay.stars,
                "rating": stay.rating,
            }
            for i, stay in enumerate(stays, 1)
        ]
        + [
            {
                "type": "stay_filter",
                "sort": understood.stay_sort,
                "priceMin": floor,
                "priceMax": cap,
                "minStars": stars,
                "relative": understood.price_relative,
            }
        ],
    )


def vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + "đ"
