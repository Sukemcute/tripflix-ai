from datetime import UTC, datetime

import httpx

from app.services.assistant.schemas import Answer, Card, SearchResponse, Section

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
