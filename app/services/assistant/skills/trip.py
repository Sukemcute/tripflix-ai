"""Skills about a reel (its itinerary, people's views, its hotel) and about a named hotel.

The reel id comes from the app (contextPostId) or from a card Tripi showed, never from the
LLM. Core answers 404 for a hidden or deleted post, so a removed reel is never described.
"""

from datetime import UTC, date, datetime
from uuid import UUID

import httpx

from app.clients.core_api import CorePost
from app.services.assistant.schemas import Answer, Card, CardLine
from app.services.summary.vi_text import normalize_text

GONE = Answer(kind="no_result", text="Reel này không còn hiển thị nữa, bạn thử reel khác nha.")


async def fetch_post(core: httpx.AsyncClient, post_id: UUID) -> CorePost | None:
    response = await core.get(f"/api/v1/posts/{post_id}")
    if response.status_code == httpx.codes.NOT_FOUND:
        return None
    response.raise_for_status()
    return CorePost.model_validate(response.json()["post"])


def matches(query: str, title: str) -> bool:
    """Does the user's name for a reel fit this title? Every word of the query, no accents."""
    words = normalize_text(query).split()
    folded = f" {normalize_text(title)} "
    useful = [w for w in words if w not in {"reel", "video", "clip", "vua", "goi", "y", "cua"}]
    return bool(useful) and all(f" {w} " in folded for w in useful)


def _stops(items, day: int) -> str:
    return "; ".join(
        " · ".join(part for part in (item.title, item.location) if part)
        for item in items
        if item.day == day
    )


async def post_itinerary(
    core: httpx.AsyncClient,
    post_id: UUID,
    *,
    day: int | None = None,
    asks_days_count: bool = False,
    reel_query: str = "",
) -> Answer:
    post = await fetch_post(core, post_id)
    if post is None:
        return GONE
    trip = post.trip_attachment
    title = post.title or (trip.destination_name if trip else "") or "Lộ trình"
    # The user named another reel than the one in view: say so, never answer for the wrong
    # one (Expo Web report P15, R14).
    if reel_query and not matches(reel_query, title):
        return Answer(
            kind="no_result",
            text=f"Reel đang mở là «{title[:80]}», không phải reel bạn vừa nhắc. "
            "Bạn mở đúng reel đó hoặc để Tripi tìm lại nha.",
            suggestions=[f"Tìm reel {reel_query[:40]}"],
        )
    if trip is None or not trip.items:
        return Answer(kind="no_result", text="Reel này chưa gắn lộ trình chi tiết.")
    days = trip.days_count or max((i.day or 0) for i in trip.items) or None
    lead = None
    if asks_days_count and days:
        lead = f"Reel này đi {days} ngày."
    elif day is not None:
        stops = _stops(trip.items, day)
        lead = (
            f"Ngày {day}: {stops}."
            if stops
            else f"Reel này chỉ có {days} ngày, không có ngày {day}."
            if days and day > days
            else f"Lộ trình chưa ghi điểm nào cho ngày {day}."
        )
    lines = [
        CardLine(
            label=f"Ngày {item.day}" if item.day else "Điểm",
            detail=" · ".join(part for part in (item.title, item.location) if part),
        )
        for item in trip.items[:12]
    ]
    return Answer(
        kind="answer",
        text=lead or "Đây là lộ trình trong reel bạn đang xem.",
        lead=lead,
        cards=[
            Card(
                ref="r1",
                id=post.id,
                kind="itinerary",
                title=title[:120],
                price_from=None,
                price_basis="unavailable",
                observed_at=datetime.now(UTC),
                lines=lines,
            )
        ],
        facts=[
            {
                "ref": "r1",
                "kind": "itinerary",
                "destination": trip.destination_name,
                "days": days,
                "hotel": trip.hotel_name,
                "askedDay": day,
                "stops": [
                    {"day": i.day, "title": i.title, "place": i.location} for i in trip.items[:12]
                ],
            }
        ],
        suggestions=["Khách sạn trong reel còn phòng không?", "Thời tiết ở đó", "Cần mang gì?"],
    )


async def post_reviews(core: httpx.AsyncClient, post_id: UUID) -> Answer:
    """The stored comment summary (TF44); never summarised again in chat."""
    response = await core.get(f"/api/v1/posts/{post_id}/ai-summary")
    # 404 means no summary yet (live run 2026-11-16), not a hidden post.
    summary = {} if response.status_code == httpx.codes.NOT_FOUND else response.json()
    if response.status_code != httpx.codes.NOT_FOUND:
        response.raise_for_status()
    takeaways = [str(t) for t in summary.get("keyTakeaways") or []][:5]
    if summary.get("status") != "ready" or not takeaways:
        return Answer(
            kind="no_result", text="Reel này chưa đủ bình luận để Tripi tóm tắt ý kiến mọi người."
        )
    return Answer(
        kind="answer",
        text="Đây là những điều người xem reel này nhắc nhiều nhất.",
        cards=[
            Card(
                ref="r1",
                id=str(post_id),
                kind="summary",
                title="Người đi rồi nói gì",
                price_from=None,
                price_basis="unavailable",
                observed_at=datetime.now(UTC),
                lines=[_line(t) for t in takeaways],
            )
        ],
        facts=[{"ref": "r1", "kind": "summary", "takeaways": takeaways}],
    )


async def reel_room(
    core: httpx.AsyncClient, post_id: UUID, check_in: date, check_out: date, adults: int
) -> Answer:
    post = await fetch_post(core, post_id)
    if post is None:
        return GONE
    attachment = post.trip_attachment
    if attachment is None or not attachment.hotel_id:
        return Answer(kind="no_result", text="Reel này chưa gắn khách sạn trên Tripflix.")
    return await hotel_room(
        core, attachment.hotel_id, check_in, check_out, adults, fallback_name=attachment.hotel_name
    )


async def named_hotel_room(
    core: httpx.AsyncClient, name: str, check_in: date, check_out: date, adults: int
) -> Answer:
    """A hotel the user called by name wins over the reel's hotel (Expo Web report R11)."""
    response = await core.get("/api/suggest", params={"q": name, "types": "hotel"})
    response.raise_for_status()
    hotels = [i for i in response.json().get("items") or [] if i.get("type") == "hotel"]
    exact = [h for h in hotels if normalize_text(h.get("name", "")) == normalize_text(name)]
    picks = exact or hotels
    if not picks:
        return Answer(kind="no_result", text=f"Tripi chưa tìm thấy «{name[:60]}» trên Tripflix.")
    if len(picks) > 1:
        names = ", ".join(str(h.get("name")) for h in picks[:3])
        return Answer(kind="clarify", text=f"Bạn hỏi khách sạn nào: {names}?")
    return await hotel_room(
        core, str(picks[0]["refId"]), check_in, check_out, adults, fallback_name=name
    )


async def hotel_room(
    core: httpx.AsyncClient,
    hotel_id: str,
    check_in: date,
    check_out: date,
    adults: int,
    *,
    fallback_name: str | None = None,
) -> Answer:
    response = await core.get(
        f"/api/hotels/{hotel_id}",
        params={
            "checkIn": check_in.isoformat(),
            "checkOut": check_out.isoformat(),
            "adults": adults,
        },
    )
    if response.status_code == httpx.codes.NOT_FOUND:
        return Answer(kind="no_result", text="Khách sạn này không còn bán trên Tripflix.")
    response.raise_for_status()
    hotel = response.json()
    name = str(hotel.get("name") or fallback_name or "Khách sạn")
    totals = [
        (plan.get("totalPrice"), plan.get("pricePerNight"))
        for room in hotel.get("rooms") or []
        if room.get("isAvailable")
        for plan in room.get("ratePlans") or []
        if plan.get("totalPrice") is not None
    ]
    is_available = bool(totals)
    total, per_night = min(totals) if totals else (None, None)
    when = f"{check_in:%d/%m/%Y}–{check_out:%d/%m/%Y}"
    # The lead names the hotel and the exact dates Core was asked, so words and card always
    # speak of the same thing (Expo Web report R11, V11).
    lead = (
        f"{name} còn phòng cho {adults} người, {when}."
        if is_available
        else f"{name} đã hết phòng cho {adults} người, {when}."
    )
    return Answer(
        kind="answer" if is_available else "no_result",
        text=lead,
        lead=lead,
        cards=[
            Card(
                ref="r1",
                id=str(hotel.get("id") or hotel_id),
                kind="stay",
                title=name,
                price_from=per_night,
                total_price=total,
                price_basis="per_night_per_room" if is_available else "unavailable",
                check_in=check_in,
                check_out=check_out,
                observed_at=datetime.now(UTC),
            )
        ],
        # No price for the Responder: prices live on the card only (Verifier V2).
        facts=[
            {
                "ref": "r1",
                "kind": "stay",
                "title": name,
                "available": is_available,
                "checkIn": f"{check_in:%d/%m}",
                "checkOut": f"{check_out:%d/%m}",
                "adults": adults,
            }
        ],
    )


def _line(text: str) -> CardLine:
    return CardLine(label=text[:160])
