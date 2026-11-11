import pytest

from app.services.summary.estimates import add_estimates, wilson
from app.services.summary.label_store import PostStats
from app.services.summary.schemas import SummaryContent, SummaryCounts, SummaryPointOut

COUNTS = SummaryCounts(comments=200, people=200, sent=200)


def _content() -> SummaryContent:
    point = SummaryPointOut(aspect="canh_quan", text="View đẹp", comment_ids=["c1"], people=30)
    return SummaryContent(pros=[point], counts=COUNTS)


def _stats(writers: int) -> PostStats:
    return PostStats(
        labelled_comments=writers,
        first_hand_comments=writers // 3,
        complaint_comments=writers // 5,
        praise_comments=writers // 2,
        writers=writers,
        first_hand_writers=writers // 3,
    )


def test_wilson_stays_inside_zero_and_one_and_brackets_the_share() -> None:
    low, share, high = wilson(30, 200)

    assert share == 0.15 and 0.10 < low < share < high < 0.21
    assert wilson(0, 200)[0] == 0.0 and wilson(200, 200)[2] == 1.0
    assert wilson(5, 0) == (0.0, 0.0, 0.0)


def test_a_big_post_gets_whole_post_counts_and_scaled_point_estimates() -> None:
    """30 of the 200 writers read say 'view đẹp'; the post has 30,000 writers."""
    content = add_estimates(_content(), _stats(30_000), sampled_writers=200)

    estimate = content.pros[0].estimate
    assert content.population is not None and content.population.writers == 30_000
    assert estimate is not None and estimate.people == 4_500
    assert estimate.low < 4_500 < estimate.high and estimate.high - estimate.low < 3_000
    assert content.pros[0].people == 30  # the exact sample count stays


@pytest.mark.parametrize("stats", [None, _stats(0)])
def test_no_label_store_counts_means_the_content_is_unchanged(stats: PostStats | None) -> None:
    assert add_estimates(_content(), stats, sampled_writers=200) == _content()


def test_a_post_read_whole_needs_no_estimate() -> None:
    content = add_estimates(_content(), _stats(150), sampled_writers=200)

    assert content.population is not None and content.pros[0].estimate is None
