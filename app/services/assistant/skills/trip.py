"""Skills about the reel the chat was opened from: its itinerary, people's views, its hotel.

The post id comes from the app (contextPostId), never from the LLM. Core answers 404 for a
hidden or deleted post, so a removed reel is never described.
"""

from datetime import UTC, date, datetime
from uuid import UUID

import httpx

from app.clients.core_api import CorePost
from app.services.assistant.schemas import Answer, Card, CardLine

GONE = Answer(kind="no_result", text="Reel này không còn hiển thị nữa, bạn thử reel khác nha.")


async def fetch_post(core: httpx.AsyncClient, post_id: UUID) -> CorePost | None:
    response = await core.get(f"/api/v1/posts/{post_id}")
    if response.status_code == httpx.codes.NOT_FOUND:
        return None
    response.raise_for_status()
    return CorePost.model_validate(response.json()["post"])


async def post_itinerary(core: httpx.AsyncClient, post_id: UUID) -> Answer:
    post = await fetch_post(core, post_id)
    if post is None:
        return GONE
    trip = post.trip_attachment
    if trip is None or not trip.items:
        return Answer(kind="no_result", text="Reel này chưa gắn lộ trình chi tiết.")
    lines = [
        CardLine(
            label=f"Ngày {item.day}" if item.day else "Điểm",
            detail=" · ".join(part for part in (item.title, item.location) if part),
        )
        for item in trip.items[:12]
    ]
    title = post.title or trip.destination_name or "Lộ trình"
    return Answer(
        kind="answer",
        text="Đây là lộ trình trong reel bạn đang xem.",
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
                "days": trip.days_count,
                "hotel": trip.hotel_name,
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


async def check_room(
    core: httpx.AsyncClient, post_id: UUID, check_in: date, check_out: date, adults: int
) -> Answer:
    post = await fetch_post(core, post_id)
    if post is None:
        return GONE
    attachment = post.trip_attachment
    hotel_id = attachment.hotel_id if attachment else None
    if attachment is None or not hotel_id:
        return Answer(kind="no_result", text="Reel này chưa gắn khách sạn trên Tripflix.")
    response = await core.get(
        f"/api/hotels/{hotel_id}",
        params={
            "checkIn": check_in.isoformat(),
            "checkOut": check_out.isoformat(),
            "adults": adults,
        },
    )
    if response.status_code == httpx.codes.NOT_FOUND:
        return Answer(kind="no_result", text="Khách sạn trong reel không còn bán trên Tripflix.")
    response.raise_for_status()
    hotel = response.json()
    totals = [
        (plan.get("totalPrice"), plan.get("pricePerNight"))
        for room in hotel.get("rooms") or []
        if room.get("isAvailable")
        for plan in room.get("ratePlans") or []
        if plan.get("totalPrice") is not None
    ]
    is_available = bool(totals)
    total, per_night = min(totals) if totals else (None, None)
    when = f"{check_in:%d/%m} – {check_out:%d/%m}"
    return Answer(
        kind="answer" if is_available else "no_result",
        text=f"Khách sạn trong reel còn phòng cho {when}."
        if is_available
        else f"Khách sạn trong reel đã hết phòng cho {when}.",
        cards=[
            Card(
                ref="r1",
                id=str(hotel.get("id") or hotel_id),
                kind="stay",
                title=str(hotel.get("name") or attachment.hotel_name or "Khách sạn"),
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
                "title": hotel.get("name"),
                "available": is_available,
                "checkIn": f"{check_in:%d/%m}",
                "checkOut": f"{check_out:%d/%m}",
                "adults": adults,
            }
        ],
    )


def _line(text: str) -> CardLine:
    return CardLine(label=text[:160])
