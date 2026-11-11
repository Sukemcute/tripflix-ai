from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# Same cap as core (Comment.MAX_BODY_LENGTH, be PR #58).
MAX_COMMENT_CHARS = 2_000


class CommentIn(BaseModel):
    """One comment as core-api sends it to POST /summarize."""

    model_config = ConfigDict(frozen=True)

    comment_id: str = Field(min_length=1)
    author_id: str = Field(min_length=1)
    parent_id: str | None = None
    body: str = Field(max_length=MAX_COMMENT_CHARS)
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
# Caps the validator trims to (V1): a JSON mode without strict schema ignores maxItems, and a
# whole run should not fail for one extra item. Evidence is high because people are counted
# from these ids (a 10-id cap failed big posts and undercounted).
MAX_EVIDENCE = 50
MAX_SAFETY_MENTIONS = 5
MAX_POINTS = 5
MAX_REALITY_GAPS = 3
MAX_TOPICS = 6
Evidence = Annotated[list[CommentCode], Field(min_length=1, max_length=MAX_EVIDENCE)]
_STRICT = ConfigDict(extra="forbid", frozen=True)

# comment_ids comes first in every item: the model picks its evidence before it writes
# (Anthropic long-context tips: extract the relevant quotes before answering).


# short: the point in a few words for the 300-char summary text, so it can hold every point
# (summary.v3). Not checked here: a missing, too long or banned one only falls back to text in
# the validator, it never fails the run.
SHORT_CHARS = 40


class AspectPoint(BaseModel):
    model_config = _STRICT
    comment_ids: Evidence
    aspect: Aspect
    text: str = Field(min_length=1, max_length=120)
    short: str | None = None


class SafetyMention(BaseModel):
    model_config = _STRICT
    comment_ids: Evidence
    text: str = Field(min_length=1, max_length=120)


class RealityGap(BaseModel):
    model_config = _STRICT
    claim_id: ClaimCode
    comment_ids: Evidence
    reality: str = Field(min_length=1, max_length=120)
    short: str | None = None


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
    safety_mentions: list[SafetyMention] = Field(max_length=MAX_SAFETY_MENTIONS)
    pros: list[AspectPoint] = Field(max_length=MAX_POINTS)
    cons: list[AspectPoint] = Field(max_length=MAX_POINTS)
    reality_gaps: list[RealityGap] = Field(max_length=MAX_REALITY_GAPS)
    topics: list[Topic] = Field(max_length=MAX_TOPICS)


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


# ---- Body of core's PUT /api/v1/posts/:postId/ai-summary (PR be #54). An API contract, so
# JSON keys are camelCase (RULES §4.1); comment ids here are the real core ids.


class _CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, frozen=True)


class PeopleEstimate(_CamelModel):
    """How many writers of the whole post likely hold a point, when only a sample was read:
    share in the sample times all writers, Wilson 95% interval. Code-made, never the LLM."""

    people: int
    low: int
    high: int


class SummaryPointOut(_CamelModel):
    aspect: Aspect
    text: str
    comment_ids: list[str]
    people: int  # counted by code (V6)
    estimate: PeopleEstimate | None = None  # only when the post has more writers than were read


class RealityGapOut(_CamelModel):
    claim: str
    reality: str
    comment_ids: list[str]
    people: int


class TopicOut(_CamelModel):
    label: str
    summary: str
    comment_ids: list[str]
    people: int
    estimate: PeopleEstimate | None = None


Labeler = Literal["model", "rules", "mixed"]


class PostPopulation(_CamelModel):
    """Counts over every labelled comment of the post (label store), next to the summary
    that read a sample. Writers are HyperLogLog estimates (~0.8% error)."""

    labelled_comments: int
    writers: int
    first_hand_writers: int
    first_hand_comments: int
    complaint_comments: int
    praise_comments: int
    is_estimate: bool = True


class SummaryCounts(_CamelModel):
    comments: int  # comments core returned
    people: int  # distinct writers left after filtering
    sent: int  # comments sent to the LLM


class SummaryContent(_CamelModel):
    pros: list[SummaryPointOut] = []
    cons: list[SummaryPointOut] = []
    reality_gaps: list[RealityGapOut] = []
    topics: list[TopicOut] = []
    counts: SummaryCounts
    needed: int | None = None  # more people needed before a summary (insufficient_data)
    # Who labelled the comments: model, rules (classifier off or failed) or mixed (a cap or a
    # partial failure). A silent fall to rules halves video-gap recall, so it must show.
    labeler: Labeler = "rules"
    population: PostPopulation | None = None


class SafetyWarning(_CamelModel):
    categories: list[str]
    comment_ids: list[str]


class SummarySafety(_CamelModel):
    warnings: list[SafetyWarning]  # first-hand: shown on the public GET
    # Hearsay held for a moderator: core stores it, its public GET leaves it out, and an
    # approved one moves to warnings (agreed with Trang, content/moderation, 2026-11-08).
    pending_warnings: list[SafetyWarning] = []


SummaryStatus = Literal["no_comments", "insufficient_data", "ready", "failed"]


class SaveSummaryRequest(_CamelModel):
    status: SummaryStatus
    summary: str | None = None
    key_takeaways: list[str] = []
    content: SummaryContent | None = None
    safety: SummarySafety | None = None
    input_hash: str | None = None
    comment_count: int = 0
    prompt_version: str | None = None
    model_name: str | None = None
    # Every comment whose text reached the LLM (after the token cut, reply parents included):
    # core holds the summary back while one of them is hidden or deleted (Trang, 2026-11-09).
    # [] means no comment text went in; None (an old row) means unknown.
    source_comment_ids: list[str] | None = None
    # Required: core's Zod rejects null and orders writes by it (saveIfNewer, be PR #58).
    # Set when the run starts reading its input, so a slow older run never overwrites a newer one.
    generated_at: AwareDatetime
