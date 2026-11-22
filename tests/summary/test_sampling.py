from datetime import UTC, datetime, timedelta

from app.services.summary.sampling import pick_for_labels
from app.services.summary.schemas import CommentIn

NOW = datetime(2026, 11, 11, tzinfo=UTC)


def _c(i: int, *, days_ago: float = 0, likes: int = 0, reply: bool = False) -> CommentIn:
    return CommentIn(
        comment_id=f"c{i}",
        author_id=f"u{i}",
        parent_id="c0" if reply else None,
        body=f"comment {i}",
        status="visible",
        like_count=likes,
        created_at=NOW - timedelta(days=days_ago),
    )


def test_a_post_under_the_cap_is_labelled_whole() -> None:
    comments = [_c(i) for i in range(10)]

    assert pick_for_labels(comments, 10) == comments


def test_older_weeks_and_replies_get_their_share_unlike_newest_n() -> None:
    """900 comments from today and 100 from last month: 'newest 100' took none of the older
    ones; the stratified sample keeps about their 10%."""
    comments = [_c(i, days_ago=0.1) for i in range(900)]
    comments += [_c(900 + i, days_ago=30) for i in range(50)]
    comments += [_c(950 + i, days_ago=30, reply=True) for i in range(50)]

    picked = pick_for_labels(comments, 100)

    old = [c for c in picked if c.created_at < NOW - timedelta(days=7)]
    assert len(picked) == 100
    assert len(old) == 10 and sum(c.parent_id is not None for c in old) == 5


def test_liked_comments_are_more_likely_in() -> None:
    comments = [_c(i, likes=500 if i < 20 else 0) for i in range(400)]

    picked = {c.comment_id for c in pick_for_labels(comments, 20)}

    assert len(picked & {f"c{i}" for i in range(20)}) >= 15


def test_safety_hits_come_first_and_the_sample_is_the_same_every_run() -> None:
    comments = [_c(i, days_ago=i % 60) for i in range(1000)]

    first = pick_for_labels(comments, 50, first={"c999", "c3"})

    assert {"c999", "c3"} <= {c.comment_id for c in first}
    assert first == pick_for_labels(comments, 50, first={"c999", "c3"})
    assert len({c.comment_id for c in first}) == 50
