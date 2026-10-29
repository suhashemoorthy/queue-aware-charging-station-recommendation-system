from fastapi.testclient import TestClient

from app.cache import StationCache
from app.main import app
from app.models import Station
from app.live_data import refresh_live_data
from app.ocpi import OCPIError, normalize_ocpi_status
from app.osm import osm_element_to_station
from app.queue_model import estimate_wait_minutes, mmc_wait_minutes


def test_osm_way_normalization_keeps_unknown_metadata_explicit():
    station = osm_element_to_station({
        "type": "way",
        "id": 42,
        "center": {"lat": 11.01, "lon": 76.96},
        "tags": {"amenity": "charging_station", "name": "OSM Hub"},
    })
    assert station is not None
    assert station.source == "OpenStreetMap"
    assert station.name == "OSM Hub"
    assert station.connector_types == []
    assert station.status == "unknown"


def test_ocpi_status_normalization():
    state = normalize_ocpi_status({
        "location_id": "LOC-1",
        "evse_uid": "EVSE-1",
        "status": "CHARGING",
        "last_updated": "2026-09-04T10:00:00Z",
    })
    assert state.source == "OCPI"
    assert state.status == "occupied"
    assert state.occupied_ports == 1


def test_cache_hash_map_merge():
    cache = StationCache()
    station = Station(
        station_id="S1", name="Station", latitude=11, longitude=76,
        operator="Test", connector_types=["CCS2"], charging_speed_kw=60,
        total_ports=2, available_ports=1, occupied_ports=1, cost_per_kwh=10,
        rating=4, reliability_score=0.9,
    )
    cache.set_station(station)
    assert cache.get_station("S1").station_id == "S1"
    assert cache.get_station("missing") is None


def test_queue_models_are_explicitly_labelled():
    wait, source = estimate_wait_minutes(0, 2, 0, 60)
    assert wait > 0
    assert source == "occupancy_estimate"
    utilization, queue_length, wait_minutes = mmc_wait_minutes(0.01, 0.05, 2)
    assert 0 < utilization < 1
    assert queue_length >= 0
    assert wait_minutes >= 0


def test_api_exposes_fallback_status():
    response = TestClient(app).post("/api/recommend", json={
        "latitude": 11.0301, "longitude": 77.0007,
        "battery_percent": 27, "battery_capacity_kwh": 60,
        "target_battery_percent": 80, "max_detour_km": 10,
        "connector_type": "CCS2",
    })
    assert response.status_code == 200
    payload = response.json()
    assert payload["data_status"]["live_data"]["source"] in {"static", "OCPI", "TomTom"}
    assert payload["recommendations"][0]["connector_compatibility"] == "compatible"


def test_provider_failure_retains_cached_live_state():
    class FailingOCPI:
        configured = True

        async def get_evse_status(self):
            raise OCPIError("test outage")

    class FailingTomTom:
        api_key = "configured-for-test"

        async def get_availability(self, station):
            raise RuntimeError("test outage")

    station = Station(
        station_id="LIVE-1", name="Live station", latitude=11, longitude=76,
        operator="Test", connector_types=["CCS2"], charging_speed_kw=60,
        total_ports=2, available_ports=1, occupied_ports=1, cost_per_kwh=10,
        rating=4, reliability_score=.9, live_data=True, live_source="OCPI",
    )
    cache = StationCache()
    cache.set_station(station)
    source = __import__("asyncio").run(
        refresh_live_data([station], cache, FailingOCPI(), FailingTomTom())
    )
    assert source == "OCPI"
    assert cache.get_station("LIVE-1").live_source == "OCPI"
