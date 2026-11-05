from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class CommentIn(BaseModel):
    """One comment as core-api sends it to POST /summarize."""

    model_config = ConfigDict(frozen=True)

    comment_id: str = Field(min_length=1)
    author_id: str = Field(min_length=1)
    parent_id: str | None = None
    # 10k chars: limit agreed with content (Thành, 2026-11-05); core enforces the same cap.
    body: str = Field(max_length=10_000)
    status: Literal["visible", "hidden", "deleted"]
    like_count: int = Field(default=0, ge=0)
    created_at: AwareDatetime
    edited_at: AwareDatetime | None = None
    is_post_author: bool = False


class ItineraryItemIn(BaseModel):
    """One itinerary item of the post (QT §2.1 itinerary_items); used to build claims."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["service", "manual"]
    place_name: str = Field(min_length=1, max_length=200)
    service_type: str | None = None


# ---- LLM output (QT Bước 12.4, BAO_CAO P8). Internal schema with the LLM, not an API contract,
# so fields stay snake_case. Limits are [HIỆU CHỈNH] from the architecture report.

# The 10 fixed aspects for pros/cons; the 11th, "khop_video", is covered by reality_gaps.
Aspect = Literal[
    "gia_ca",
    "dong_duc",
    "ve_sinh",
    "phuc_vu",
    "do_an",
    "vi_tri_di_lai",
    "an_toan",
    "thoi_tiet_mua",
    "phong_o",
    "canh_quan",
]
CommentCode = Annotated[str, Field(pattern=r"^c[0-9]+$")]  # temporary IDs from pii.pseudonymize
ClaimCode = Annotated[str, Field(pattern=r"^clm_[0-9]+$")]  # IDs from claims.build_claims
Evidence = Annotated[list[CommentCode], Field(min_length=1, max_length=10)]
_STRICT = ConfigDict(extra="forbid", frozen=True)

# comment_ids comes first in every item: the model picks its evidence before it writes
# (Anthropic long-context tips: extract the relevant quotes before answering).


class AspectPoint(BaseModel):
    model_config = _STRICT
    comment_ids: Evidence
    aspect: Aspect
    text: str = Field(min_length=1, max_length=120)


class SafetyMention(BaseModel):
    model_config = _STRICT
    comment_ids: Evidence
    text: str = Field(min_length=1, max_length=120)


class RealityGap(BaseModel):
    model_config = _STRICT
    claim_id: ClaimCode
    comment_ids: Evidence
    reality: str = Field(min_length=1, max_length=120)


class Topic(BaseModel):
    model_config = _STRICT
    comment_ids: Evidence
    label: str = Field(min_length=1, max_length=40)
    summary: str = Field(min_length=1, max_length=200)


class Excluded(BaseModel):
    model_config = _STRICT
    video_reaction_ids: list[CommentCode]
    speculation_ids: list[CommentCode]


class SummaryLlmOutput(BaseModel):
    """What the LLM must return. Exclusions and safety come first, then the synthesis."""

    model_config = _STRICT
    excluded: Excluded
    safety_mentions: list[SafetyMention] = Field(max_length=5)
    pros: list[AspectPoint] = Field(max_length=5)
    cons: list[AspectPoint] = Field(max_length=5)
    reality_gaps: list[RealityGap] = Field(max_length=3)
    topics: list[Topic] = Field(max_length=6)


# Claude structured outputs reject length, count and numeric constraints; OpenAI strict mode
# wants every property required. Send only the safe subset; Pydantic checks the rest (V1).
_UNSUPPORTED = {"minLength", "maxLength", "minItems", "maxItems", "pattern", "minimum", "maximum"}


def build_llm_json_schema() -> dict[str, Any]:
    """JSON Schema of SummaryLlmOutput that both Claude and OpenAI strict mode accept."""
    return _strip(SummaryLlmOutput.model_json_schema())


def _strip(node: Any) -> Any:
    if isinstance(node, dict):
        cleaned = {
            # property names and $defs names are not keywords: keep them, clean their schemas
            k: {name: _strip(sub) for name, sub in v.items()}
            if k in ("properties", "$defs")
            else _strip(v)
            for k, v in node.items()
            if k not in _UNSUPPORTED
        }
        if cleaned.get("type") == "object" and "properties" in cleaned:
            cleaned["additionalProperties"] = False
            cleaned["required"] = list(cleaned["properties"])
        return cleaned
    if isinstance(node, list):
        return [_strip(v) for v in node]
    return node
