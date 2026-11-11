import pytest

from app.services.summary.estimates import PostStats, SampleShape, add_estimates, wilson
from app.services.summary.schemas import SummaryContent, SummaryCounts, SummaryPointOut

COUNTS = SummaryCounts(comments=3_000, people=200, sent=200)


def _content(cited: int) -> SummaryContent:
    ids = [f"t1-{i}" for i in range(cited)]
    point = SummaryPointOut(aspect="canh_quan", text="View đẹp", comment_ids=ids, people=cited)
    return SummaryContent(pros=[point], counts=COUNTS)


def _shape(*, is_whole: bool = False) -> SampleShape:
    """2,000 writers in core's sample; 200 of them experienced (tier 1), 100 of those sent;
    1,500 others (tier 3), 100 of those sent."""
    tier1 = {f"a1-{i}": 200 / 100 for i in range(100)}
    tier3 = {f"a3-{i}": 1_500 / 100 for i in range(100)}
    return SampleShape(
        comments=3_000,
        writers=2_000,
        has_post_author=True,
        is_whole=is_whole,
        weights=tier1 | tier3,
        author_of={f"t1-{i}": f"a1-{i}" for i in range(100)},
        sent_writers=200,
    )


def test_wilson_stays_inside_zero_and_one_and_brackets_the_share() -> None:
    low, high = wilson(0.15, 200)

    assert 0.10 < low < 0.15 < high < 0.21
    assert wilson(0.0, 200)[0] == 0.0 and wilson(1.0, 200)[1] == 1.0
    assert wilson(0.5, 0) == (0.0, 0.0)


def test_sent_writers_count_for_their_tier_not_for_the_whole_post() -> None:
    """20 cited experienced writers stand for 40 of the sample's 2,000 writers: 2%.
    The post has 20,001 writers, the author among them: about 400. Scaling 20 of the 200 sent
    writers straight to the post gave 2,000, five times too many."""
    content = add_estimates(_content(20), PostStats(comments=60_000, writers=20_001), _shape())

    estimate = content.pros[0].estimate
    assert estimate is not None and estimate.people == 400
    assert estimate.low < 400 < estimate.high
    assert content.pros[0].people == 20  # the exact count on what was read stays
    assert content.population is not None
    assert (content.population.writers, content.population.sampled_writers) == (20_001, 2_000)


def test_agreeing_replies_beyond_the_cited_writers_count_once_each() -> None:
    point = _content(20).pros[0].model_copy(update={"people": 25})
    content = _content(20).model_copy(update={"pros": [point]})

    estimate = add_estimates(content, PostStats(60_000, 20_001), _shape()).pros[0].estimate

    assert estimate is not None and estimate.people == 450  # (40 + 5) / 2,000 of 20,000


def test_no_core_counts_means_the_content_is_unchanged() -> None:
    assert add_estimates(_content(20), None, _shape()) == _content(20)


def test_a_post_read_whole_gets_counts_but_no_estimate() -> None:
    content = add_estimates(_content(20), PostStats(3_000, 2_001), _shape(is_whole=True))

    assert content.population is not None and content.pros[0].estimate is None


@pytest.mark.parametrize("cited", [0, 100])
def test_estimates_never_leave_the_post(cited: int) -> None:
    content = add_estimates(_content(cited), PostStats(60_000, 20_001), _shape())

    estimate = content.pros[0].estimate
    assert estimate is not None and 0 <= estimate.low <= estimate.people <= estimate.high
    assert estimate.high <= 20_000
