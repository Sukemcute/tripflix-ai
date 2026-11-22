"""Sample intercity bus routes (plan B4): route and stations only, always "for reference"."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from app.services.summary.vi_text import normalize_text

CATALOG = Path(__file__).with_name("transport.v1.yaml")
# The same city under the names people use ("sg", "hcm", "sài gòn").
CITY_ALIASES = {"sg": "tp hcm", "sai gon": "tp hcm", "hcm": "tp hcm", "ho chi minh": "tp hcm"}


@dataclass(frozen=True)
class BusRoute:
    from_city: str
    to_city: str
    from_station: str
    to_station: str
    kind: str


@cache
def _catalog() -> dict:
    return yaml.safe_load(CATALOG.read_text(encoding="utf-8"))


def attribution() -> str:
    return str(_catalog()["attribution"])


def _key(city: str) -> str:
    folded = normalize_text(city).replace("thanh pho ", "").strip()
    return CITY_ALIASES.get(folded, folded)


def bus_routes(origin: str, destination: str) -> list[BusRoute]:
    """Routes between two cities in either direction; empty when the catalog has none."""
    wanted = (_key(origin), _key(destination))
    found = []
    for row in _catalog()["routes"]:
        ends = (_key(row["from"]), _key(row["to"]))
        if ends == wanted:
            found.append(
                BusRoute(
                    row["from"], row["to"], row["from_station"], row["to_station"], row["kind"]
                )
            )
        elif ends == wanted[::-1]:
            found.append(
                BusRoute(
                    row["to"], row["from"], row["to_station"], row["from_station"], row["kind"]
                )
            )
    return found
