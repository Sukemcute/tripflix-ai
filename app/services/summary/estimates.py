"""Scale point counts from the sample the LLM read to the whole post.

A point's people are counted among the writers sent to the LLM (about 200 at most). On a post
with 30,000 writers, "3 people" is right for the sample and wrong for the post. The share in the
sample is an estimate of the share in the post (Cochran: the sample size, not the post size,
sets the error); the Wilson score interval keeps the range inside 0..1 for small counts.
"""

import math

from app.services.summary.label_store import PostStats
from app.services.summary.schemas import PeopleEstimate, PostPopulation, SummaryContent

Z_95 = 1.96


def wilson(k: int, n: int, z: float = Z_95) -> tuple[float, float, float]:
    """Share k/n and its Wilson interval (low, share, high)."""
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = min(k, n) / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), p, min(1.0, centre + half)


def to_population(stats: PostStats) -> PostPopulation:
    return PostPopulation(
        labelled_comments=stats.labelled_comments,
        writers=stats.writers,
        first_hand_writers=stats.first_hand_writers,
        first_hand_comments=stats.first_hand_comments,
        complaint_comments=stats.complaint_comments,
        praise_comments=stats.praise_comments,
    )


def add_estimates(
    content: SummaryContent, stats: PostStats | None, sampled_writers: int
) -> SummaryContent:
    """Population counts on the content, and per-point estimates when the post has more writers
    than the run read. shortcut: video gaps keep exact first-hand counts; scale them by
    first-hand writers once the sample records how many first-hand writers it holds."""
    if stats is None or stats.labelled_comments == 0:
        return content
    population = to_population(stats)
    if population.writers <= sampled_writers or sampled_writers <= 0:
        return content.model_copy(update={"population": population})

    def estimate(people: int) -> PeopleEstimate:
        low, share, high = wilson(people, sampled_writers)
        w = population.writers
        return PeopleEstimate(
            people=round(share * w), low=math.floor(low * w), high=math.ceil(high * w)
        )

    return content.model_copy(
        update={
            "population": population,
            "pros": [p.model_copy(update={"estimate": estimate(p.people)}) for p in content.pros],
            "cons": [p.model_copy(update={"estimate": estimate(p.people)}) for p in content.cons],
            "topics": [
                t.model_copy(update={"estimate": estimate(t.people)}) for t in content.topics
            ],
        }
    )
