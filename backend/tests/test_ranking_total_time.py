import csv
from pathlib import Path

import pytest

from app.algorithms import filter_by_connector
from app.models import Station
from app.recommender import normalize_weights, rank_candidates

ORIGIN = (11.0100, 76.9550)


def make_station(station_id, speed, cost, *, lat=11.0168, lon=76.9558, available=2, total=2,
                 wait=0.0, queue=0, connectors=("CCS2",), connector_class="DC", rating=0.0,
                 reliability=None, status="operational") -> Station:
    return Station(
        station_id=station_id, name=f"Test {station_id}", latitude=lat, longitude=lon,
        connector_types=list(connectors), connector_class=connector_class,
        charging_speed_kw=speed, cost_per_kwh=cost,
        total_ports=total, available_ports=available, occupied_ports=total - available,
        queue_length=queue, estimated_wait_min=wait, status=status,
        dynamic_data_source="synthetic_demo_state", rating=rating,
        reliability_score=reliability,
    )


def rank(stations, **kwargs):
    kwargs.setdefault("top_k", 10)
    return rank_candidates(stations, *ORIGIN, **kwargs)


def test_small_battery_does_not_reward_a_faster_rated_charger():
    # 3.7 kWh battery accepts ~3.7 kW, so 25 kW and 60 kW stations charge equally fast.
    # The cheaper one must win; a rated-kW ranking would have preferred the 60 kW one.
    cheap_25 = make_station("CHEAP25", 25, 14)
    pricey_60 = make_station("PRICEY60", 60, 22)
    result = rank([pricey_60, cheap_25], battery_capacity_kwh=3.7)
    assert result[0].station_id == "CHEAP25"
    assert result[0].charge_time_min == result[1].charge_time_min
    assert result[0].limited_by == "battery"


def test_large_battery_rewards_the_faster_charger_even_if_costlier():
    slow_cheap = make_station("SLOW", 25, 20)
    fast = make_station("FAST", 60, 21)
    result = rank([slow_cheap, fast], battery_capacity_kwh=60)
    assert result[0].station_id == "FAST"


def test_total_time_includes_wait_so_a_free_station_beats_a_nearer_busy_one():
    near_busy = make_station("NEAR", 50, 18, lat=11.0105, available=0, wait=40, queue=2)
    far_free = make_station("FAR", 50, 18, lat=11.0300, available=2, wait=0)
    result = rank([near_busy, far_free], battery_capacity_kwh=40)
    assert result[0].station_id == "FAR"
    near = next(r for r in result if r.station_id == "NEAR")
    assert near.total_time_min == pytest.approx(
        near.travel_time_min + near.estimated_wait_min + near.charge_time_min, abs=0.15
    )


def test_a_full_station_cannot_have_zero_wait():
    full = make_station("FULL", 50, 18, available=0, wait=0.0)  # inconsistent demo row
    result = rank([full], battery_capacity_kwh=40)
    assert result[0].estimated_wait_min > 0


def test_missing_rating_and_reliability_do_not_cap_the_score():
    a = make_station("A", 50, 18)
    result = rank([a])
    assert result[0].score_percent == 100.0  # was capped at 85% before
    assert set(result[0].score_breakdown) == {"total_time", "cost", "availability"}


def test_weights_are_renormalised_over_available_criteria():
    base = {"total_time": 0.55, "cost": 0.15, "availability": 0.10, "reliability": 0.15, "rating": 0.05}
    weights = normalize_weights(base, {"total_time", "cost", "availability"})
    assert sum(weights.values()) == pytest.approx(1.0)
    assert weights["total_time"] == pytest.approx(0.55 / 0.80)


def test_urgency_shifts_weight_to_time_and_availability_and_still_sums_to_one():
    base = {"total_time": 0.55, "cost": 0.15, "availability": 0.10, "reliability": 0.15, "rating": 0.05}
    present = set(base)
    calm = normalize_weights(base, present, "LOW")
    urgent = normalize_weights(base, present, "CRITICAL")
    assert sum(urgent.values()) == pytest.approx(1.0)
    assert urgent["total_time"] > calm["total_time"]
    assert urgent["cost"] < calm["cost"]


def test_unknown_power_station_is_skipped_not_crashed():
    unknown = make_station("NOPOWER", 0, 18)
    ok = make_station("OK", 50, 18)
    assert [r.station_id for r in rank([unknown, ok])] == ["OK"]


def test_unverified_connector_is_kept_flagged_and_penalised():
    listed = make_station("LISTED", 50, 18)
    unlisted = make_station("UNLISTED", 50, 18, connectors=(), connector_class="UNKNOWN")
    result = rank([unlisted, listed])
    assert [r.station_id for r in result] == ["LISTED", "UNLISTED"]
    flagged = result[1]
    assert flagged.connector_compatibility == "unverified"
    assert "Connector type not verified" in flagged.reasons
    assert flagged.score == pytest.approx(result[0].score * 0.85, rel=0.02)


def test_filter_by_connector_statuses():
    compatible = make_station("OK", 50, 18)
    wrong = make_station("WRONG", 50, 18, connectors=("CHAdeMO",))
    unlisted = make_station("NONE", 50, 18, connectors=(), connector_class="UNKNOWN")
    down = make_station("DOWN", 50, 18, status="temporarily_unavailable")
    kept, status = filter_by_connector([compatible, wrong, unlisted, down], "CCS2")
    assert status == {"OK": "compatible", "WRONG": "incompatible",
                      "NONE": "unverified", "DOWN": "unavailable"}
    assert [s.station_id for s in kept] == ["OK", "NONE"]
    kept_strict, _ = filter_by_connector([compatible, unlisted], "CCS2", include_unverified=False)
    assert [s.station_id for s in kept_strict] == ["OK"]


def test_ties_are_deterministic():
    twins = [make_station(f"T{i}", 50, 18) for i in range(4)]
    first = [r.station_id for r in rank(twins, top_k=3)]
    second = [r.station_id for r in rank(list(twins), top_k=3)]
    assert first == second == ["T0", "T1", "T2"]


def test_demo_csv_state_is_physically_consistent():
    path = Path(__file__).resolve().parents[1] / "data" / "coimbatore_ev_stations_replica_demo_synthetic.csv"
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    assert rows
    for r in rows:
        total, avail = int(r["sim_total_ports"]), int(r["sim_available_ports"])
        occ, oos = int(r["sim_occupied_ports"]), int(r["sim_out_of_service_ports"] or 0)
        queue, wait = int(r["sim_queue_length"]), float(r["sim_estimated_wait_min"] or 0)
        sid = r["station_id"]
        assert avail + occ + oos == total, sid
        if queue > 0:
            assert avail == 0, f"{sid}: queue while a port is free"
        if avail > 0:
            assert wait == 0, f"{sid}: wait while a port is free"
        if r["sim_station_status"] == "operational" and avail == 0:
            assert wait > 0, f"{sid}: no free port but zero wait"
