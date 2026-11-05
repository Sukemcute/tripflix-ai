"""Integrity of the 15 labelled seed posts (CHECKLIST P7). Labels follow Key Point Analysis
(Bar-Haim et al., ACL 2020): each expected point is mapped to the comments that support it.
"""

import json
from collections import Counter
from pathlib import Path
from typing import Any, get_args

import pytest

from app.services.summary.lexicon import load
from app.services.summary.schemas import Aspect, CommentIn, ItineraryItemIn

SEED_DIR = Path(__file__).resolve().parents[2] / "evals" / "summary" / "seed"
POSTS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(SEED_DIR.glob("*.json"))}
STATUSES = {"no_comments", "insufficient_data", "ready"}


def _cited(labels: dict[str, Any]) -> list[str]:
    groups = labels["points"] + labels["reality_gaps"] + labels["topics"]
    ids = [i for g in groups for i in g["comment_ids"]]
    return (
        ids
        + list(labels["must_not_cite"])
        + labels["not_safety"]
        + [s["comment_id"] for s in labels["safety"]]
    )


def test_the_mix_required_by_the_checklist() -> None:
    scenarios = Counter(p["scenario"] for p in POSTS.values())

    assert len(POSTS) == 15
    assert scenarios["reality_gap"] == 4
    assert scenarios["below_threshold"] == 3
    assert (
        scenarios["safety_first_hand"] + scenarios["safety_hearsay"] + scenarios["safety_mixed"]
        == 3
    )
    assert scenarios["spam"] == 2
    assert scenarios["video_only"] == 2
    assert scenarios["injection"] == 1
    assert sum(len(p["labels"]["topics"]) >= 2 for p in POSTS.values()) >= 3


@pytest.mark.parametrize("name", list(POSTS))
def test_post_is_simulated_and_fits_the_input_schema(name: str) -> None:
    post = POSTS[name]
    comments = [CommentIn.model_validate(c) for c in post["comments"]]
    [ItineraryItemIn.model_validate(i) for i in post["itinerary"]]
    ids = [c.comment_id for c in comments]

    assert post["is_simulated"] is True
    assert len(ids) == len(set(ids))
    assert all(c.parent_id in ids for c in comments if c.parent_id)
    assert post["labels"]["status"] in STATUSES


@pytest.mark.parametrize("name", list(POSTS))
def test_every_label_points_to_a_real_comment_and_two_people(name: str) -> None:
    post = POSTS[name]
    labels = post["labels"]
    author = {c["comment_id"]: c["author_id"] for c in post["comments"]}

    assert set(_cited(labels)) <= set(author)
    for group in labels["points"] + labels["reality_gaps"] + labels["topics"]:
        assert len({author[i] for i in group["comment_ids"]}) >= 2, group
    assert {p["aspect"] for p in labels["points"]} <= set(get_args(Aspect))
    assert {s["category"] for s in labels["safety"]} <= set(load("safety").groups)
    assert {s["visibility"] for s in labels["safety"]} <= {"public", "pending_review"}
    if labels["status"] != "ready":
        assert not labels["points"] and not labels["reality_gaps"] and not labels["topics"]
