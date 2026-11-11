from datetime import UTC, datetime

from app.clients.core_api import CoreComment, CorePost, CoreSampleComment, CoreTripAttachment
from app.services.summary.core_adapter import (
    build_caption,
    build_itinerary,
    convert_comments,
    convert_sample,
)

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


def test_comment_saved_before_the_2000_cap_is_cut_not_rejected() -> None:
    old = _core("guest").model_copy(update={"body": "a" * 5_000})

    [converted] = convert_comments([old], "owner")

    assert len(converted.body) == 2_000


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


def _flat(i: int, created: datetime) -> CoreComment:
    return CoreComment(
        id=f"c-{i}", author_id=f"u-{i}", body=f"Phòng {i}", created_at=created, updated_at=created
    )


def test_a_sample_is_put_in_the_flat_order_so_a_small_post_keeps_its_input() -> None:
    """Core samples in hash order; the flat list is newest first. Same order, same hash."""
    times = [datetime(2026, 11, d, tzinfo=UTC) for d in (1, 3, 3, 2)]
    flat = sorted(
        (_flat(i, t) for i, t in enumerate(times)),
        key=lambda c: (c.created_at, c.id),
        reverse=True,
    )
    shuffled = [flat[2], flat[0], flat[3], flat[1]]
    sample = [
        CoreSampleComment(id=c.id, author_id=c.author_id, body=c.body, created_at=c.created_at)
        for c in shuffled
    ]

    assert convert_sample(sample, "owner") == convert_comments(flat, "owner")


def test_a_sampled_reply_carries_its_parent_text_and_edit_time() -> None:
    item = CoreSampleComment(
        id="c-2",
        author_id="owner",
        parent_comment_id="c-1",
        parent_comment_body="Có ai ở đây chưa?",
        body="Mình ở rồi",
        created_at=CREATED,
        edited_at=EDITED,
    )

    [reply] = convert_sample([item], "owner")

    assert reply.parent_body == "Có ai ở đây chưa?" and reply.edited_at == EDITED
    assert reply.is_post_author
