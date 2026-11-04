from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from app.services.summary.filters import filter_comments
from app.services.summary.schemas import CommentIn

NOW = datetime(2026, 11, 4, tzinfo=UTC)
GOOD = "Phòng sạch sẽ, nhân viên dễ thương"


def comment(comment_id: str = "c1", **overrides: Any) -> CommentIn:
    fields: dict[str, Any] = {
        "comment_id": comment_id,
        "author_id": f"u-{comment_id}",
        "body": GOOD,
        "status": "visible",
        "created_at": NOW - timedelta(days=1),
    }
    return CommentIn(**(fields | overrides))


def reason(**overrides: Any) -> str | None:
    return filter_comments([comment(**overrides)], NOW).dropped.get("c1")


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"status": "hidden"}, "L1"),
        ({"status": "deleted"}, "L1"),
        ({"created_at": NOW - timedelta(days=366)}, "L2"),
        ({"is_post_author": True}, "L3"),
        ({"body": "😍😍🔥"}, "L4"),
        ({"body": "Đẹp quá"}, "L5"),
        ({"body": "Đặt phòng giá rẻ tại https://abc.xyz nha"}, "L6"),
        ({"body": "Phòng đẹp lắm, xem thêm ở vinpearl-sale.vn"}, "L6"),
        ({"body": "Phòng đẹp lắm, vào abc chấm com mà xem"}, "L6"),
        ({"body": "Nhạc hay quá ad ơi"}, "L12"),
        ({"body": "Ước được đi 1 lần"}, "L12"),
        ({"body": "Clip hài quá cười đau bụng luôn"}, "L12"),
    ],
)
def test_rule_drops_with_its_code(overrides: dict[str, Any], code: str) -> None:
    assert reason(**overrides) == code


@pytest.mark.parametrize(
    "overrides",
    [
        {},
        {"created_at": NOW - timedelta(days=365)},  # exactly one year still counts
        {"body": "Ngộ độc"},  # short but safety: L5 must not drop it
        {"body": "Nhạc hay mà phòng bẩn"},  # mixed: talks about the real room
        {"body": "Flycam mượt nhưng thất vọng"},  # mixed: complaint
        {"body": "Giá 1.500k một đêm, hơi đắt"},  # a dot in a price is not a link
    ],
)
def test_rule_keeps_usable_comment(overrides: dict[str, Any]) -> None:
    assert reason(**overrides) is None


def test_reply_is_judged_on_its_own_length() -> None:
    """L11: a reply counts only if it passes L5 by itself."""
    parent = comment("c1")
    short_reply = comment("c2", parent_id="c1", body="Đúng rồi")
    long_reply = comment("c3", parent_id="c1", body="Mình cũng thấy hồ bơi hơi nhỏ")

    result = filter_comments([parent, short_reply, long_reply], NOW)

    assert result.dropped == {"c2": "L5"}
    assert {c.comment_ids for c in result.candidates} == {("c1",), ("c3",)}


def test_same_text_from_many_accounts_keeps_earliest_copy_as_suspect() -> None:
    """L8: copy-paste seeding across accounts."""
    first = comment("c1", body="Resort đẹp xuất sắc!!!", created_at=NOW - timedelta(hours=3))
    copy = comment("c2", body="resort dep xuat sac", created_at=NOW - timedelta(hours=1))
    other = comment("c3")

    result = filter_comments([copy, first, other], NOW)

    assert result.dropped == {"c2": "L8"}
    by_author = {c.author_id: c for c in result.candidates}
    assert by_author["u-c1"].suspect is True
    assert by_author["u-c3"].suspect is False


def test_same_author_comments_merge_into_one_voice() -> None:
    """L9: one author, many comments -> one candidate; their own repeat is dropped."""
    early = comment("c1", author_id="u1", body="Phòng sạch, view biển", like_count=2)
    late = comment("c2", author_id="u1", body="Bữa sáng ít món lắm", like_count=7, created_at=NOW)
    repeat = comment("c3", author_id="u1", body="Phòng sạch, view biển!!")

    result = filter_comments([late, repeat, early], NOW)

    assert result.dropped == {"c3": "L9"}
    [merged] = result.candidates
    assert merged.comment_ids == ("c1", "c2")
    assert merged.text == "Phòng sạch, view biển | Bữa sáng ít món lắm"
    assert (merged.like_count, merged.created_at, merged.suspect) == (7, NOW, False)


@pytest.mark.parametrize(
    "overrides",
    [
        {"like_count": -1},
        {"status": "spam"},
        {"created_at": datetime(2026, 11, 4)},  # no time zone
        {"body": "a" * 10_001},
        {"comment_id": ""},
    ],
)
def test_bad_input_is_rejected_at_the_boundary(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        comment(**overrides)
