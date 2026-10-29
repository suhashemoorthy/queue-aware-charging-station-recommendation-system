"""Every algorithm from the comparison study can be chosen, and each follows its own rule."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import Station
from app.strategies import ALGORITHMS, run_algorithm

ORIGIN = (11.0100, 76.9550)

REQUEST = {
    "latitude": 11.0242, "longitude": 76.9344, "origin_id": "PSG_COLLEGE_OF_TECHNOLOGY",
    "battery_percent": 20, "target_battery_percent": 80, "battery_capacity_kwh": 60,
    "max_detour_km": 10, "connector_type": "CCS2",
}


def make(station_id, speed, cost, lat, *, available=1, total=2, queue=0, wait=0.0, connectors=("CCS2",)):
    return Station(
        station_id=station_id, name=f"Station {station_id}", latitude=lat, longitude=76.9558,
        connector_types=list(connectors), connector_class="DC" if connectors else "UNKNOWN",
        charging_speed_kw=speed, cost_per_kwh=cost, total_ports=total, available_ports=available,
        occupied_ports=total - available, queue_length=queue, estimated_wait_min=wait,
        dynamic_data_source="synthetic_demo_state",
    )


def stations():
    return [
        make("NEAR_SLOW", 25, 20.0, 11.0110, available=0, total=1, queue=2, wait=40.0),
        make("MID_FAST", 60, 24.0, 11.0200, available=1, total=2),
        make("FAR_CHEAP", 30, 12.0, 11.0400, available=2, total=2),
        make("FAR_FREE", 50, 18.0, 11.0450, available=3, total=3),
    ]


def ids(recs):
    return [r.station_id for r in recs]


def run(algorithm, **kwargs):
    return run_algorithm(algorithm, stations(), *ORIGIN, top_k=4, battery_capacity_kwh=60, **kwargs)


def test_registry_covers_every_algorithm_in_the_comparison_table():
    assert set(ALGORITHMS) == {
        "new_ranker", "legacy_ranker", "topsis", "generalized_cost", "min_total_time",
        "nearest", "max_availability", "fastest_rated_kw", "cheapest", "random",
    }


@pytest.mark.parametrize("algorithm", list(ALGORITHMS))
def test_every_algorithm_returns_complete_cards_for_the_same_stations(algorithm):
    recs = run(algorithm)
    assert 1 <= len(recs) <= 4
    assert all(r.algorithm == algorithm for r in recs)
    assert [r.rank for r in recs] == list(range(1, len(recs) + 1))
    for r in recs:  # the charge numbers shown are the same battery-aware ones for every algorithm
        assert r.charge_time_min > 0 and r.delivered_kw > 0
        assert r.total_time_min == pytest.approx(r.travel_time_min + r.estimated_wait_min + r.charge_time_min, abs=0.2)


def test_nearest_orders_by_travel_time():
    recs = run("nearest")
    assert ids(recs)[0] == "NEAR_SLOW"
    assert [r.travel_time_min for r in recs] == sorted(r.travel_time_min for r in recs)
    assert recs[0].score_percent is None and "travel" in recs[0].score_note


def test_cheapest_orders_by_tariff():
    recs = run("cheapest")
    assert ids(recs)[0] == "FAR_CHEAP"
    assert [r.cost_per_kwh for r in recs] == sorted(r.cost_per_kwh for r in recs)


def test_fastest_rated_orders_by_rated_power():
    recs = run("fastest_rated_kw")
    assert ids(recs)[0] == "MID_FAST"
    assert [r.charging_speed_kw for r in recs] == sorted((r.charging_speed_kw for r in recs), reverse=True)


def test_max_availability_prefers_fully_free_stations_and_puts_the_full_one_last():
    recs = run("max_availability")
    ratios = [r.available_ports / r.total_ports for r in recs]
    assert ratios == sorted(ratios, reverse=True)
    assert set(ids(recs)[:2]) == {"FAR_CHEAP", "FAR_FREE"}  # both 100% free; nearer one first
    assert ids(recs)[-1] == "NEAR_SLOW"


def test_min_total_time_uses_rated_kw_not_the_battery_model():
    # A 3.7 kWh battery cannot use 60 kW, but this baseline believes the rating.
    a, b = make("SLOW", 25, 18.0, 11.0110), make("RATED_FAST", 60, 18.0, 11.0110)
    recs = run_algorithm("min_total_time", [a, b], *ORIGIN, battery_capacity_kwh=3.7)
    assert ids(recs)[0] == "RATED_FAST"
    battery_aware = run_algorithm("new_ranker", [a, b], *ORIGIN, battery_capacity_kwh=3.7)
    assert battery_aware[0].charge_time_min == battery_aware[1].charge_time_min  # truly the same


def test_topsis_returns_scores_in_descending_order():
    recs = run("topsis")
    scores = [r.score_percent for r in recs]
    assert all(0 <= s <= 100 for s in scores) and scores == sorted(scores, reverse=True)
    assert "closeness" in recs[0].score_note


def test_generalized_cost_orders_by_time_plus_cost_over_value_of_time():
    recs = run("generalized_cost")
    values = [r.total_time_min + r.session_cost_inr / 5.0 for r in recs]
    assert values == sorted(values)
    assert recs[0].score_percent is None and "min-equivalent" in recs[0].score_note


def test_random_is_reproducible_for_the_same_request():
    assert ids(run("random")) == ids(run("random"))


def test_legacy_ranker_keeps_its_own_score_and_gets_comparable_charge_numbers():
    recs = run("legacy_ranker")
    assert all(r.score_percent is not None for r in recs)
    assert all(r.charge_time_min > 0 for r in recs)


def test_new_ranker_is_unchanged_by_going_through_the_selector():
    direct = run_algorithm("new_ranker", stations(), *ORIGIN, top_k=4, battery_capacity_kwh=60)
    assert [r.score for r in direct] == sorted((r.score for r in direct), reverse=True)


def test_unknown_algorithm_raises():
    with pytest.raises(KeyError):
        run_algorithm("magic", stations(), *ORIGIN)


# ------------------------------------------------------------------------------- the API
def test_api_lists_all_algorithms():
    body = TestClient(app).get("/api/algorithms").json()
    assert body["default"] == "new_ranker"
    assert {a["id"] for a in body["algorithms"]} == set(ALGORITHMS)
    assert all(a["label"] and a["group"] and a["description"] for a in body["algorithms"])


@pytest.mark.parametrize("algorithm", list(ALGORITHMS))
def test_api_recommend_works_for_every_algorithm(algorithm):
    response = TestClient(app).post("/api/recommend", json={**REQUEST, "algorithm": algorithm})
    assert response.status_code == 200
    body = response.json()
    assert body["algorithm"] == algorithm and body["algorithm_label"] == ALGORITHMS[algorithm][0]
    assert 1 <= len(body["recommendations"]) <= 3
    assert all(r["algorithm"] == algorithm for r in body["recommendations"])


def test_api_default_algorithm_is_the_new_ranker():
    body = TestClient(app).post("/api/recommend", json=REQUEST).json()
    assert body["algorithm"] == "new_ranker"


def test_api_rejects_an_unknown_algorithm():
    response = TestClient(app).post("/api/recommend", json={**REQUEST, "algorithm": "magic"})
    assert response.status_code == 422


def test_api_compare_runs_every_algorithm_on_the_same_request():
    body = TestClient(app).post("/api/compare", json=REQUEST).json()
    assert [c["algorithm"] for c in body["cases"]] == list(ALGORITHMS)
    assert all(1 <= len(c["recommendations"]) <= 3 for c in body["cases"])
    assert body["required_energy_kwh"] == 36.0
