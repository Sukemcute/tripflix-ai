import json
from typing import Any

import pytest
from pydantic import ValidationError

from app.services.summary.schemas import SummaryLlmOutput, build_llm_json_schema

VALID: dict[str, Any] = {
    "excluded": {"video_reaction_ids": ["c9"], "speculation_ids": []},
    "safety_mentions": [{"comment_ids": ["c3"], "text": "Có người kể bị ngộ độc sau buffet."}],
    "pros": [{"comment_ids": ["c1", "c2"], "aspect": "canh_quan", "text": "View biển đẹp."}],
    "cons": [{"comment_ids": ["c4", "c5"], "aspect": "phuc_vu", "text": "Check-in chờ lâu."}],
    "reality_gaps": [{"claim_id": "clm_1", "comment_ids": ["c1"], "reality": "Phòng nhìn ra núi."}],
    "topics": [
        {"comment_ids": ["c6", "c7"], "label": "Nên đi giờ nào", "summary": "Gợi ý đi sớm."}
    ],
}
_UNSUPPORTED = {"minLength", "maxLength", "minItems", "maxItems", "pattern", "minimum", "maximum"}


def _objects(node: Any) -> list[dict[str, Any]]:
    """Every object schema in the tree."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            found.append(node)
        for value in node.values():
            found += _objects(value)
    elif isinstance(node, list):
        for value in node:
            found += _objects(value)
    return found


def _keywords(node: Any) -> set[str]:
    """Schema keywords used anywhere, skipping property and $defs names."""
    if isinstance(node, list):
        return set().union(*(_keywords(v) for v in node)) if node else set()
    if not isinstance(node, dict):
        return set()
    keys = set(node)
    for k, v in node.items():
        children = v.values() if k in ("properties", "$defs") else [v]
        for child in children:
            keys |= _keywords(child)
    return keys


def test_valid_output_parses() -> None:
    parsed = SummaryLlmOutput.model_validate_json(json.dumps(VALID))

    assert parsed.pros[0].aspect == "canh_quan"


def test_schema_sent_to_the_llm_uses_only_the_safe_subset() -> None:
    """Claude rejects length/count constraints; OpenAI strict wants every property required."""
    schema = build_llm_json_schema()

    assert not _keywords(schema) & _UNSUPPORTED
    for obj in _objects(schema):
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])


def test_evidence_comes_before_the_sentence_in_each_item() -> None:
    defs = build_llm_json_schema()["$defs"]

    for name in ("AspectPoint", "SafetyMention", "Topic"):
        assert next(iter(defs[name]["properties"])) == "comment_ids"


@pytest.mark.parametrize(
    "patch",
    [
        {"pros": [{"comment_ids": ["cmt_123"], "aspect": "canh_quan", "text": "x"}]},  # real id
        {"pros": [{"comment_ids": ["c1"], "aspect": "khop_video", "text": "x"}]},  # not in pros
        {"pros": [{"comment_ids": [], "aspect": "canh_quan", "text": "x"}]},  # no evidence
        {"pros": [{"comment_ids": ["c1"], "aspect": "canh_quan", "text": "x" * 121}]},
        {"topics": [VALID["topics"][0]] * 7},  # more than 6 topics
        {"reality_gaps": [{"claim_id": "c1", "comment_ids": ["c1"], "reality": "x"}]},
        {"pros": [{**VALID["pros"][0], "people": 3}]},  # extra field (LLM counting people)
    ],
)
def test_output_breaking_the_limits_is_rejected(patch: dict[str, Any]) -> None:
    """Limits the API cannot enforce are checked here (V1)."""
    with pytest.raises(ValidationError):
        SummaryLlmOutput.model_validate(VALID | patch)
