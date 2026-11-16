"""The 40 labelled Tripi cases must keep passing in ci mode (fixed plans, fake Core)."""

import asyncio

from evals.assistant.run import load_cases, run_ci


def test_every_labelled_case_matches_in_ci_mode():
    cases = load_cases()
    assert len(cases) == 40
    assert asyncio.run(run_ci(cases)) == 0
