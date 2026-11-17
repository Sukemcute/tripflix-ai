"""The labelled Tripi cases must keep passing in ci mode (fixed plans, fake Core)."""

import asyncio

import pytest

from evals.assistant.run import load_cases, read_jsonl, run_ci


@pytest.mark.parametrize(("version", "count"), [("v1", 40), ("v2", 30), ("v3", 30)])
def test_every_labelled_case_matches_in_ci_mode(version, count):
    cases = load_cases(version)
    assert len(cases) == count
    assert asyncio.run(run_ci(cases)) == 0


def test_chains_are_well_formed():
    for chain in read_jsonl("chains.v1.jsonl"):
        assert chain["turns"] and all("intent" in t["expect"] for t in chain["turns"])
