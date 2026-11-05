from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field


class CommentIn(BaseModel):
    """One comment as core-api sends it to POST /summarize."""

    model_config = ConfigDict(frozen=True)

    comment_id: str = Field(min_length=1)
    author_id: str = Field(min_length=1)
    parent_id: str | None = None
    # shortcut: 10k cap proposed by Claude, confirm the real limit with core at integration.
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
