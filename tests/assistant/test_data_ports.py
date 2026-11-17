"""Data ports of Stage B (plan B4): places from Core, estimated legs, sample bus routes."""

import asyncio

import httpx
import pytest

from app.clients.places import CorePlaces
from app.services.assistant.route import estimate_leg, haversine_km
from app.services.assistant.transport import attribution, bus_routes

SAIGON = (10.7769, 106.7009)
VUNG_TAU = (10.3460, 107.0843)
HAI_DANG = (10.3333, 107.0778)
BAI_SAU = (10.3487, 107.0938)


def test_straight_line_distance_matches_known_cities():
    assert 60 < haversine_km(SAIGON, VUNG_TAU) < 70  # about 63 km as the crow flies


def test_intercity_legs_use_highway_speed_and_say_they_are_estimates():
    leg = estimate_leg(SAIGON, VUNG_TAU)
    assert 75 < leg.km < 90 and 75 < leg.minutes < 95
    assert leg.is_estimate


def test_short_legs_use_city_speed():
    leg = estimate_leg(HAI_DANG, BAI_SAU)
    assert leg.km < 5 and leg.minutes >= leg.km * 60 / 30 - 1


@pytest.mark.parametrize(
    ("origin", "destination", "stations"),
    [
        ("sài gòn", "Vũng Tàu", ("Bến xe Miền Đông", "Bến xe Vũng Tàu")),
        ("vung tau", "hcm", ("Bến xe Vũng Tàu", "Bến xe Miền Đông")),  # either direction
    ],
)
def test_bus_routes_are_found_by_the_names_people_use(origin, destination, stations):
    route = bus_routes(origin, destination)[0]
    assert (route.from_station, route.to_station) == stations


def test_no_route_is_invented_and_every_route_is_labelled():
    assert bus_routes("TP.HCM", "Hà Giang") == []
    assert "Tham khảo" in attribution()


def test_core_places_reads_points_with_coordinates():
    seen: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        item = {"id": "osm:1", "name": "Hải Đăng Vũng Tàu", "kind": "see", "lat": 10.33,
                "lng": 107.07, "city": "Vũng Tàu", "tags": ["view"], "popularity": 0.9}  # fmt: skip
        return httpx.Response(200, json={"items": [item], "attribution": "OSM"})

    async def run():
        transport = httpx.MockTransport(handle)
        async with httpx.AsyncClient(base_url="https://core.test", transport=transport) as core:
            return await CorePlaces(core).search(city="Vũng Tàu", kinds=["see", "food"])

    (place,) = asyncio.run(run())
    assert (place.name, place.kind, place.latitude, place.tags) == (
        "Hải Đăng Vũng Tàu",
        "see",
        10.33,
        ("view",),
    )
    assert seen["city"] == "Vũng Tàu" and seen["kinds"] == "see,food"
