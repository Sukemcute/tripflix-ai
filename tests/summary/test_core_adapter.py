from datetime import UTC, datetime

from app.clients.core_api import CoreComment, CorePost, CoreTripAttachment
from app.services.summary.core_adapter import build_caption, build_itinerary, convert_comments

CREATED = datetime(2026, 11, 4, tzinfo=UTC)
EDITED = datetime(2026, 11, 5, tzinfo=UTC)


def _core(author: str, *, is_edited: bool = False, likes: int = 0) -> CoreComment:
    return CoreComment(
        id="c-1",
        author_id=author,
        parent_comment_id="c-0",
        body="Phòng đẹp",
        like_count=likes,
        is_edited=is_edited,
        created_at=CREATED,
        updated_at=EDITED,
    )


def test_comments_mark_the_post_author_and_edits() -> None:
    comments = [_core("owner"), _core("guest", is_edited=True, likes=7)]
    [own, edited] = convert_comments(comments, "owner")

    assert own.is_post_author and own.edited_at is None and own.parent_id == "c-0"
    assert not edited.is_post_author and edited.edited_at == EDITED
    assert own.status == "visible" and own.like_count == 0
    assert edited.like_count == 7  # core's likeCount (be PR #58) feeds tier-3 ranking


def test_hotel_becomes_the_service_claim_and_title_joins_the_caption() -> None:
    post = CorePost(
        id="p",
        author_id="owner",
        title="Đà Nẵng 3N2Đ",
        body="Phòng view biển",
        trip_attachment=CoreTripAttachment(hotel_name="Vinpearl Beach Đà Nẵng"),
    )

    [hotel] = build_itinerary(post)

    assert hotel.kind == "service" and hotel.place_name == "Vinpearl Beach Đà Nẵng"
    assert build_caption(post) == "Đà Nẵng 3N2Đ\nPhòng view biển"
    assert build_itinerary(CorePost(id="p", author_id="o")) == []
