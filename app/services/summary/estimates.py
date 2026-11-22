"""Scale point counts from the writers the LLM read to the whole post.

A point's people are counted among the writers sent to the LLM (about 200). Those are no
random draw: the selection takes experienced writers first, then complaints (selection.py),
so their share of the sent writers overstates their share of the post. Two steps fix it:
1. core's sample is random over the post (Thành, PR be #128: hashtext(id || seed)), and
2. post-stratification (Holt and Smith 1979): a sent writer of tier t stands for N_t / n_t
   writers of the sample (N_t candidates of that tier, n_t of them sent).
The weighted share times the post's writers is the estimate. The Wilson score interval uses
n = writers sent, the ones actually read, so it stays honest about how little was read.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass

from app.services.summary.schemas import (
    PeopleEstimate,
    PostPopulation,
    SummaryContent,
    SummaryPointOut,
    TopicOut,
)

Z_95 = 1.96


@dataclass(frozen=True)
class PostStats:
    """Whole-post counts from core: visible comments only, the post author's included."""

    comments: int
    writers: int


@dataclass(frozen=True)
class SampleShape:
    """What one run read, to scale from it."""

    comments: int  # comments read
    writers: int  # distinct writers read, the post author left out
    has_post_author: bool  # the post author commented: core's writers count them
    is_whole: bool  # every comment of the post read and every candidate sent: counts are exact
    weights: Mapping[str, float]  # sent writer -> writers of the sample they stand for
    author_of: Mapping[str, str]  # sent comment id -> its writer
    sent_writers: int


def wilson(share: float, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval (low, high) of a share measured on n."""
    if n <= 0:
        return 0.0, 0.0
    p = min(max(share, 0.0), 1.0)
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def add_estimates(
    content: SummaryContent, stats: PostStats | None, shape: SampleShape
) -> SummaryContent:
    """Whole-post counts on the content, and a per-point estimate unless the run read it all."""
    if stats is None:
        return content
    population = PostPopulation(
        comments=stats.comments,
        writers=stats.writers,
        sampled_comments=shape.comments,
        sampled_writers=shape.writers,
    )
    if shape.is_whole or shape.writers <= 0:
        return content.model_copy(update={"population": population})
    post_writers = max(stats.writers - shape.has_post_author, shape.writers)

    def estimate(point: SummaryPointOut | TopicOut) -> PeopleEstimate:
        cited = {shape.author_of[i] for i in point.comment_ids if i in shape.author_of}
        # agreeing replies (people beyond the cited writers) are votes: weight 1
        weighted = sum(shape.weights.get(a, 1.0) for a in cited) + max(0, point.people - len(cited))
        share = min(weighted / shape.writers, 1.0)
        low, high = wilson(share, shape.sent_writers)
        return PeopleEstimate(
            people=round(share * post_writers),
            low=math.floor(low * post_writers),
            high=math.ceil(high * post_writers),
        )

    return content.model_copy(
        update={
            "population": population,
            "pros": [p.model_copy(update={"estimate": estimate(p)}) for p in content.pros],
            "cons": [p.model_copy(update={"estimate": estimate(p)}) for p in content.cons],
            "topics": [t.model_copy(update={"estimate": estimate(t)}) for t in content.topics],
        }
    )
