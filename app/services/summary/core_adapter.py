"""Core-api records -> the pipeline's input schemas (BAO_CAO "Ghép nối với core")."""

from collections.abc import Sequence

from app.clients.core_api import CoreComment, CorePost
from app.services.summary.schemas import MAX_COMMENT_CHARS, CommentIn, ItineraryItemIn

_PLACE_NAME_MAX = 200


def convert_comments(comments: Sequence[CoreComment], post_author_id: str) -> list[CommentIn]:
    """Core only lists live comments (deleted ones are gone), so every one is visible.

    Rows written before core lowered its cap to 2,000 can still be longer (the column is text):
    cut them so one old comment does not fail the whole post at the schema.
    """
    return [
        CommentIn(
            comment_id=c.id,
            author_id=c.author_id,
            parent_id=c.parent_comment_id,
            body=c.body[:MAX_COMMENT_CHARS],
            status="visible",
            like_count=c.like_count,
            created_at=c.created_at,
            edited_at=c.updated_at if c.is_edited else None,
            is_post_author=c.author_id == post_author_id,
        )
        for c in comments
    ]


def build_caption(post: CorePost) -> str:
    return "\n".join(part for part in (post.title, post.body) if part)


def build_itinerary(post: CorePost) -> list[ItineraryItemIn]:
    """The booked hotel is the one service claim; day items are free text (caption rules)."""
    trip = post.trip_attachment
    if trip is None or not trip.hotel_name:
        return []
    return [
        ItineraryItemIn(
            kind="service", place_name=trip.hotel_name[:_PLACE_NAME_MAX], service_type="Khách sạn"
        )
    ]
