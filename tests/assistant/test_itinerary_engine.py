"""Itinerary Engine (plan B5): checked with simulated Vũng Tàu points (approximate coordinates)."""

from datetime import date
from itertools import permutations

from app.clients.places import PointOfInterest
from app.services.assistant.itinerary import (
    MAX_KM_PER_DAY,
    _loop_km,
    build_itinerary,
    follow_reel,
)

STAY = (10.3480, 107.0890)  # near Bãi Sau


def poi(pid, name, lat, lng, kind="see", tags=(), popularity=0.5):
    return PointOfInterest(pid, name, kind, lat, lng, "Vũng Tàu", tuple(tags), popularity)


HAI_DANG = poi("p1", "Hải Đăng", 10.3333, 107.0778, tags=("viewpoint",), popularity=0.9)
NGHINH_PHONG = poi("p2", "Mũi Nghinh Phong", 10.3236, 107.0843, tags=("sunset",), popularity=0.8)
TUONG_CHUA = poi("p3", "Tượng Chúa Kitô", 10.3271, 107.0860, tags=("viewpoint",), popularity=0.85)
BAI_SAU = poi("p4", "Bãi Sau", 10.3487, 107.0938, tags=("beach",), popularity=0.9)
BACH_DINH = poi("p5", "Bạch Dinh", 10.3530, 107.0680, tags=("museum", "indoor"), popularity=0.6)
HO_MAY = poi("p6", "Hồ Mây", 10.3460, 107.0710, tags=("park",), popularity=0.7)
LONG_HAI = poi("p7", "Long Hải", 10.3880, 107.2370, tags=("beach",), popularity=0.4)  # far
QUAN_AN = poi("f1", "Quán hải sản Bãi Trước", 10.3450, 107.0720, kind="food", popularity=0.7)
CAFE = poi("f2", "Cafe view biển", 10.3330, 107.0830, kind="cafe", popularity=0.6)
ALL = [HAI_DANG, NGHINH_PHONG, TUONG_CHUA, BAI_SAU, BACH_DINH, HO_MAY, LONG_HAI, QUAN_AN, CAFE]


def names(day):
    return [s.place.name for s in day.stops]


def test_two_days_three_sights_each_plus_a_meal_and_no_place_twice():
    plan = build_itinerary(ALL, base=STAY, days=2, start=date(2026, 11, 21))
    assert len(plan.days) == 2
    assert all(len(day.stops) == 4 for day in plan.days)  # 3 sights + dinner
    every = [s.place.id for day in plan.days for s in day.stops]
    assert len(every) == len(set(every))
    assert plan.days[1].day == date(2026, 11, 22)
    assert plan.days[0].stops[-1].slot == "tối" and plan.days[0].stops[-1].place.kind in {
        "food",
        "cafe",
    }


def test_each_day_is_the_shortest_loop_from_the_stay_up_to_time_of_day_rules():
    plan = build_itinerary([HAI_DANG, TUONG_CHUA, HO_MAY], base=STAY, days=1)
    sights = [s.place for s in plan.days[0].stops]
    best = min(_loop_km(STAY, order) for order in permutations(sights))
    assert abs(_loop_km(STAY, sights) - best) < 1e-9


def test_sunset_goes_last_and_beach_goes_first():
    plan = build_itinerary([NGHINH_PHONG, BAI_SAU, HAI_DANG], base=STAY, days=1)
    order = names(plan.days[0])
    assert order[0] == "Bãi Sau" and order[-1] == "Mũi Nghinh Phong"


def test_rain_moves_indoor_stops_first_and_says_so():
    plan = build_itinerary([BAI_SAU, BACH_DINH, HAI_DANG], base=STAY, days=1, rain_by_day=[80])
    assert names(plan.days[0])[0] == "Bạch Dinh"
    assert "mưa" in plan.days[0].notes[0]


def test_a_day_never_goes_over_the_distance_cap():
    plan = build_itinerary(ALL, base=STAY, days=1, pace="packed")
    assert plan.days[0].km <= MAX_KM_PER_DAY
    assert "Long Hải" not in names(plan.days[0])


def test_interests_pick_matching_places_first():
    plan = build_itinerary(ALL, base=STAY, days=1, interests=["beach"])
    assert "Bãi Sau" in names(plan.days[0])


def test_half_days_get_fewer_sights():
    plan = build_itinerary(ALL, base=STAY, days=2, half_days=[1])
    assert len([s for s in plan.days[0].stops if s.place.kind == "see"]) == 2


def test_every_leg_is_an_estimate_and_the_plan_says_so():
    plan = build_itinerary(ALL, base=STAY, days=1)
    assert all(s.leg.is_estimate for s in plan.days[0].stops)
    assert "ước tính" in plan.assumptions[0]


def test_no_places_means_no_invented_stops():
    plan = build_itinerary([], base=STAY, days=2)
    assert all(day.stops == () for day in plan.days)
    assert any("Chưa có điểm" in a for a in plan.assumptions)


def test_follow_reel_keeps_the_author_order():
    plan = follow_reel([[TUONG_CHUA, BAI_SAU, HAI_DANG]], base=STAY)
    assert names(plan.days[0]) == ["Tượng Chúa Kitô", "Bãi Sau", "Hải Đăng"]
