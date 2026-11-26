"""Destination catalog and trip preferences (consult intent, TF31)."""

import re

from app.services.assistant.destinations import destinations_by_id, merge_prefs
from app.services.assistant.schemas import TravelPrefs, TripContext


def test_catalog_loads_and_is_valid() -> None:
    catalog = destinations_by_id()
    assert len(catalog) >= 40
    for destination_id, destination in catalog.items():
        assert re.fullmatch(r"[a-z0-9-]+", destination_id)
        assert destination.id == destination_id
        assert destination.name.strip()
        assert all(1 <= month <= 12 for month in destination.good_months)
        assert 2 <= len(destination.highlights) <= 4
        assert not any(re.search(r"\d", text) for text in destination.highlights)
    assert {d.region for d in catalog.values()} == {"bac", "trung", "nam", "tay-nguyen"}


def test_catalog_has_core_places() -> None:
    names = {key: place.name for key, place in destinations_by_id().items()}
    expected = {
        "da-lat": "Đà Lạt",
        "vung-tau": "Vũng Tàu",
        "nha-trang": "Nha Trang",
        "da-nang": "Đà Nẵng",
        "phu-quoc": "Phú Quốc",
        "quy-nhon": "Quy Nhơn",
        "sa-pa": "Sa Pa",
        "ha-giang": "Hà Giang",
        "hoi-an": "Hội An",
        "ninh-binh": "Ninh Bình",
    }
    assert {key: names.get(key) for key in expected} == expected


def test_merge_prefs_new_wins_empty_keeps_old() -> None:
    old = TravelPrefs(vibe=["quiet"], terrain=["beach"], nights=2)
    new = TravelPrefs(terrain=["mountain"], mood="đang buồn")
    merged = merge_prefs(old, new)
    assert merged.vibe == ["quiet"]
    assert merged.terrain == ["mountain"]
    assert merged.nights == 2
    assert merged.mood == "đang buồn"
    assert merge_prefs(None, new) == new


def test_trip_context_round_trips_prefs() -> None:
    context = TripContext(prefs=TravelPrefs(vibe=["quiet"], budget_per_person=2_000_000))
    dumped = context.model_dump(mode="json", by_alias=True)
    assert dumped["prefs"]["vibe"] == ["quiet"]
    assert dumped["prefs"]["budgetPerPerson"] == 2_000_000
    assert TripContext.model_validate(dumped) == context
