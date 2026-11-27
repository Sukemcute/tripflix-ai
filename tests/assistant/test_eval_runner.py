"""The eval runner counts tokens per LLM call; calls answered by code ("rules") do not count."""

import logging

from app.clients.llm.base import LlmResult
from app.services.assistant.controller import EMPTY_OUTPUT, empty_output
from evals.assistant.run import print_token_averages, summarize_tokens, watch_recalls


def test_empty_output_matches_eval_plan():
    out = empty_output("greeting")
    assert out.intent == "greeting"
    assert EMPTY_OUTPUT["intent"] == "search"  # the base the intent is laid over
    dumped = out.model_dump()
    for name, value in EMPTY_OUTPUT.items():
        if name != "intent":
            assert dumped[name] == value, name
    assert dumped["missing"] == "none" and dumped["day_ref"] == "none"
    assert dumped["query"] == "" and dumped["is_rude"] is False and dumped["interests"] == []


def _result(model: str, tokens_in: int, tokens_out: int) -> LlmResult:
    return LlmResult(output="", model_name=model, input_tokens=tokens_in, output_tokens=tokens_out)


def test_summarize_tokens_skips_rules():
    results = [_result("rules", 0, 0), _result("gpt-5-nano", 100, 20)]
    assert summarize_tokens(results) == (1, 120, 120)


def test_summarize_tokens_all_rules_is_zero():
    assert summarize_tokens([_result("rules", 0, 0)] * 3) == (0, 0, 0)
    assert summarize_tokens([]) == (0, 0, 0)


def test_recall_counter_counts_recalled_turns():
    counter = watch_recalls()
    log = logging.getLogger("app.services.assistant.understand")
    log.info("chat.controller.modules", extra={"modules": ["reel"], "recalled": True})
    log.info("chat.controller.modules", extra={"modules": [], "recalled": False})
    log.removeHandler(counter)
    assert (counter.recalls, counter.turns) == (1, 2)


def test_recall_counter_ignores_injection_warning():
    counter = watch_recalls()
    log = logging.getLogger("app.services.assistant.understand")
    log.warning("chat.injection.suspected", extra={"groups": ["override"]})
    log.removeHandler(counter)
    assert (counter.recalls, counter.turns) == (0, 0)


def test_token_averages_count_a_recalled_turn_as_two_calls(capsys):
    counter = watch_recalls()
    log = logging.getLogger("app.services.assistant.understand")
    log.info("chat.controller.modules", extra={"modules": ["reel"], "recalled": True})
    log.removeHandler(counter)
    print_token_averages([_result("gpt-5-nano", 180, 20)], counter)  # two calls of 100 tokens
    assert "tokens/LLM call 100 (2 calls)" in capsys.readouterr().out
