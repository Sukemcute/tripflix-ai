"""The labelled Tripi cases must keep passing in ci mode (fixed plans, fake Core)."""

import asyncio

import pytest

from evals.assistant.run import load_cases, read_jsonl, run_ci


@pytest.mark.parametrize(
    ("version", "count"),
    [
        ("v1", 40),
        ("v2", 30),
        ("v3", 30),
        ("v4", 12),
        ("v5", 11),
        ("v6", 10),
        ("v7", 4),
        ("v8", 6),
        ("v9", 20),
        ("v10", 8),
    ],
)
def test_every_labelled_case_matches_in_ci_mode(version, count):
    cases = load_cases(version)
    assert len(cases) == count
    # Live mode groups the score by tag; a case without one crashed the v9 live run at the end.
    assert all("tags" in case for case in cases)
    assert asyncio.run(run_ci(cases)) == 0


def test_chains_are_well_formed():
    for chain in [c for n in (1, 2, 3, 4, 5, 6, 7, 8) for c in read_jsonl(f"chains.v{n}.jsonl")]:
        assert chain["turns"] and all("intent" in t["expect"] for t in chain["turns"])


@pytest.mark.parametrize("intent", ["search", "find_stay", "clarify"])
def test_travel_regression_cases_accept_legitimate_ci_alternatives(intent):
    cases = [c for c in load_cases("v9") if c["id"].startswith("scope-travel-regression-")]
    for case in cases:
        case["expect"]["controller"]["intent"] = intent
    assert asyncio.run(run_ci(cases)) == 0


@pytest.mark.parametrize("intent", ["refusal", "off_topic"])
def test_travel_regression_cases_reject_out_of_scope_answers(intent):
    cases = [c for c in load_cases("v9") if c["id"].startswith("scope-travel-regression-")]
    for case in cases:
        case["expect"]["controller"]["intent"] = intent
    assert asyncio.run(run_ci(cases)) == 1
