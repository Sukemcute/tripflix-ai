"""Points of interest for Tripi's itineraries: Core discovery `GET /api/places` (plan B1).

Core keeps the places (OpenStreetMap data, ODbL); ai-service only reads them per turn and
keeps nothing (RULES §10). The app must show the attribution next to any list of places.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import httpx

ATTRIBUTION = "© OpenStreetMap contributors (ODbL)"


@dataclass(frozen=True)
class PointOfInterest:
    id: str
    name: str
    kind: str  # see, food, cafe, lodging
    latitude: float
    longitude: float
    city: str
    tags: tuple[str, ...] = ()
    popularity: float = 0.0


class PlacesClient(Protocol):
    async def search(
        self,
        *,
        city: str = "",
        near: tuple[float, float] | None = None,
        kinds: Sequence[str] = (),
        radius_km: float = 15,
        limit: int = 40,
    ) -> list[PointOfInterest]: ...


class CorePlaces:
    def __init__(self, core: httpx.AsyncClient) -> None:
        self.core = core

    async def search(
        self,
        *,
        city: str = "",
        near: tuple[float, float] | None = None,
        kinds: Sequence[str] = (),
        radius_km: float = 15,
        limit: int = 40,
    ) -> list[PointOfInterest]:
        params: dict[str, str | int | float] = {"radiusKm": radius_km, "limit": limit}
        if city:
            params["city"] = city
        if near:
            params["near"] = f"{near[0]:.5f},{near[1]:.5f}"
        if kinds:
            params["kinds"] = ",".join(kinds)
        response = await self.core.get("/api/places", params=params)
        response.raise_for_status()
        return [
            PointOfInterest(
                id=str(item["id"]),
                name=str(item["name"]),
                kind=str(item["kind"]),
                latitude=float(item["lat"]),
                longitude=float(item["lng"]),
                city=str(item.get("city") or ""),
                tags=tuple(str(t) for t in item.get("tags") or ()),
                popularity=float(item.get("popularity") or 0),
            )
            for item in response.json().get("items") or []
        ]
