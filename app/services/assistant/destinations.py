"""Curated destination catalog Tripi advises from (consult intent), and trip-preference merging."""

import re
from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.assistant.schemas import Terrain, TravelPrefs, Vibe

CATALOG = Path(__file__).with_name("destinations.v1.yaml")


class Destination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    name: str = Field(min_length=1)
    region: Literal["bac", "trung", "nam", "tay-nguyen"]
    terrain: list[Terrain] = Field(min_length=1)
    vibe: list[Vibe] = Field(min_length=1)
    good_months: list[int]
    highlights: list[str] = Field(min_length=2, max_length=4)

    @field_validator("good_months")
    @classmethod
    def check_months(cls, months: list[int]) -> list[int]:
        if not months or any(not 1 <= month <= 12 for month in months):
            raise ValueError("good_months must be months 1-12")
        return months

    @field_validator("highlights")
    @classmethod
    def check_highlights(cls, highlights: list[str]) -> list[str]:
        # A digit would be a price, a time or a date that can go stale; the Verifier drops them.
        if any(not text.strip() or re.search(r"\d", text) for text in highlights):
            raise ValueError("highlights must be non-empty and contain no digits")
        return highlights


@cache
def destinations_by_id() -> dict[str, Destination]:
    data = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    by_id: dict[str, Destination] = {}
    for raw in data["destinations"]:
        destination = Destination.model_validate(raw)
        if destination.id in by_id:
            raise ValueError(f"duplicate destination id: {destination.id}")
        by_id[destination.id] = destination
    return by_id


def merge_prefs(old: TravelPrefs | None, new: TravelPrefs) -> TravelPrefs:
    """New values win; an empty value never erases what Tripi already remembers."""
    if old is None:
        return new
    fields = {
        name: getattr(new, name)
        for name in TravelPrefs.model_fields
        if getattr(new, name) not in ([], None, "")
    }
    return old.model_copy(update=fields)
