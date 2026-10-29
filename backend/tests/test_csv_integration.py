import asyncio
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.algorithms import (
    apply_road_network_distance,
    connectors_compatible,
    haversine_distance,
)
from app import main as main_module
from app.config import get_settings
from app.main import app
from app.repository import DATA_FILE, StationRepository, load_verified_origins
from app.routing import RoutingService


def test_csv_dataset_is_validated_and_indexed():
    repository = StationRepository()
    stations = repository.all()

    assert len(stations) == 47
    assert repository.get("CBE001").source_name == "ZigWheels"
    assert repository.get("CBE003").charging_speed_kw == 30
    assert repository.get("CBE048").dynamic_data_source == "synthetic_demo_state"
    assert repository.get("CBE001").estimated_wait_min == 0
    assert all(station.station_id.startswith("CBE") for station in stations)
    assert all(-90 <= station.latitude <= 90 for station in stations)
    assert all(-180 <= station.longitude <= 180 for station in stations)
    assert all(station.available_ports <= station.total_ports for station in stations)
    assert all(station.occupied_ports <= station.total_ports for station in stations)


def test_connector_aliases_are_normalized():
    assert connectors_compatible("CCS2", ["CCS-II"])
    assert connectors_compatible("Type2", ["AC TYPE 2"])
    assert not connectors_compatible("CCS2", ["CHAdeMO"])


def test_csv_ids_do_not_use_obsolete_study_graph_station_mapping():
    station = StationRepository().get("CBE001")
    origin = (11.0055, 76.9537)

    apply_road_network_distance([station], *origin)

    assert station.route_source == "haversine_estimate"
    # Fallback road distance = straight-line distance x circuity factor (default 1.3).
    assert station.road_distance_km == pytest.approx(
        get_settings().road_circuity_factor
        * haversine_distance(*origin, station.latitude, station.longitude)
    )
    assert station.travel_time_min == pytest.approx(
        station.road_distance_km / get_settings().fallback_speed_kmh * 60
    )


def test_verified_coordinate_sidecar_overlays_without_changing_csv(tmp_path):
    sidecar = tmp_path / "verified.json"
    sidecar.write_text(
        '{"CBE010":{"latitude":11.0159,"longitude":76.9647,'
        '"source":"verified_manual","note":"checked against station entrance"}}',
        encoding="utf-8",
    )

    repository = StationRepository(
        path=DATA_FILE,
        verified_coordinates_path=sidecar,
    )
    verified = repository.get("CBE010")
    original = StationRepository().get("CBE010")

    assert verified.coordinate_verified is True
    assert verified.coordinate_source == "verified_manual"
    assert verified.latitude == 11.0159
    assert verified.longitude == 76.9647
    assert original.coordinate_verified is False
    assert original.coordinate_source == "synthetic_locality_estimate"


def test_verified_origin_sidecar_validates_origin_sources(tmp_path):
    sidecar = tmp_path / "origins.json"
    sidecar.write_text(
        '{"PSG_COLLEGE_OF_TECHNOLOGY":{"latitude":11.0242,'
        '"longitude":76.9344,"source":"verified_manual"}}',
        encoding="utf-8",
    )

    origins = load_verified_origins(sidecar)

    assert origins["PSG_COLLEGE_OF_TECHNOLOGY"] == {
        "latitude": 11.0242,
        "longitude": 76.9344,
        "source": "verified_manual",
    }


def test_osrm_api_requires_both_verified_endpoints(monkeypatch):
    original_station = main_module.station_cache.get_station("CBE010")
    verified_station = original_station.model_copy(
        update={"coordinate_verified": True},
        deep=True,
    )
    main_module.station_cache.set_station(verified_station)
    captured = {}

    async def fake_route_many(latitude, longitude, stations):
        captured["origin"] = (latitude, longitude)
        captured["ids"] = {station.station_id for station in stations}
        return {
            station.station_id: {
                "distance_km": 4.25,
                "travel_time_min": 20.0,
                "source": "OSRM",
            }
            for station in stations
        }

    monkeypatch.setattr(main_module.settings, "routing_mode", "osrm")
    monkeypatch.setattr(
        main_module,
        "verified_origins",
        {
            "PSG_COLLEGE_OF_TECHNOLOGY": {
                "latitude": 11.025,
                "longitude": 76.935,
                "source": "verified_manual",
            }
        },
    )
    monkeypatch.setattr(main_module.routing, "route_many", fake_route_many)
    # The test is about route fields flowing through, not about who ranks top 3,
    # so ask the ranker for every candidate. (It used to break whenever the demo
    # state of CBE010 changed.)
    original_run = main_module.run_algorithm
    monkeypatch.setattr(
        main_module,
        "run_algorithm",
        lambda *args, **kwargs: original_run(*args, **{**kwargs, "top_k": 100}),
    )

    try:
        response = TestClient(app).post(
            "/api/recommend",
            json={
                "latitude": 11.0242,
                "longitude": 76.9344,
                "origin_id": "PSG_COLLEGE_OF_TECHNOLOGY",
                "battery_percent": 20,
                "target_battery_percent": 80,
                "connector_type": "CCS2",
                "max_detour_km": 10,
            },
        )
    finally:
        main_module.station_cache.set_station(original_station)

    assert response.status_code == 200
    assert captured["origin"] == (11.025, 76.935)
    assert "CBE010" in captured["ids"]
    recommendation = next(
        item for item in response.json()["recommendations"]
        if item["station_id"] == "CBE010"
    )
    assert recommendation["route_source"] == "OSRM"
    assert recommendation["road_distance_km"] == 4.25
    assert recommendation["travel_time_min"] == 20.0


def test_osrm_matrix_returns_km_and_minutes_and_omits_unreachable(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "code": "Ok",
                "distances": [[4250, None]],
                "durations": [[1200, None]],
            }

    class Client:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, url, params):
            assert "/table/v1/driving/" in url
            assert params["annotations"] == "distance,duration"
            return Response()

    monkeypatch.setattr("app.routing.httpx.AsyncClient", Client)
    stations = StationRepository().all()[:2]
    routing = RoutingService("osrm", "https://router.example")
    routes = asyncio.run(routing.route_many(11.0, 76.9, stations))

    assert routes[stations[0].station_id] == {
        "distance_km": 4.25,
        "travel_time_min": 20.0,
        "source": "OSRM",
    }
    assert stations[1].station_id not in routes


def test_recommendation_uses_internal_capacity_default():
    response = TestClient(app).post(
        "/api/recommend",
        json={
            "latitude": 11.0242,
            "longitude": 76.9344,
            "battery_percent": 20,
            "target_battery_percent": 80,
            "connector_type": "CCS2",
            "max_detour_km": 10,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["required_energy_kwh"] == 36.0
    assert len(payload["recommendations"]) <= 3
    assert all(
        item["dynamic_data_source"] == "synthetic_demo_state"
        for item in payload["recommendations"]
    )
    first = payload["recommendations"][0]
    navigation_url = first["navigation_url"]
    destination = parse_qs(urlparse(navigation_url).query)["destination"][0]
    assert urlparse(navigation_url).netloc == "www.google.com"
    assert "/maps/dir/" in urlparse(navigation_url).path
    assert first["name"] in destination
    assert first["address"] in destination
    assert str(first["latitude"]) not in destination
    assert str(first["longitude"]) not in destination
