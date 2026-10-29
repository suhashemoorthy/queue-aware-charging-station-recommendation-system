from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .algorithms import (
    apply_road_network_distance,
    filter_by_connector,
    spatial_filter,
)
from .cache import StationCache
from .collector import StationCollector
from .models import (
    AlgorithmCase,
    CompareResponse,
    RecommendationRequest,
    RecommendationResponse,
)
from .repository import (
    DATA_FILE,
    VERIFIED_COORDINATES_FILE,
    VERIFIED_ORIGINS_FILE,
    StationRepository,
    load_verified_origins,
)
from .reservations import ReservationManager, adjust_for_reservations
from .routes_reservations import build_router
from .routing import RoutingService
from .strategies import ALGORITHMS, run_algorithm
from .tomtom import (
    TomTomClient,
    update_station_from_tomtom,
)


settings = get_settings()

repository = StationRepository(
    path=Path(settings.station_data_path)
    if settings.station_data_path
    else DATA_FILE,
    verified_coordinates_path=Path(settings.verified_station_coordinates_path)
    if settings.verified_station_coordinates_path
    else VERIFIED_COORDINATES_FILE,
)
verified_origins = load_verified_origins(
    Path(settings.verified_origin_coordinates_path)
    if settings.verified_origin_coordinates_path
    else VERIFIED_ORIGINS_FILE
)
station_cache = StationCache()
station_cache.set_stations(repository.all())
collector = StationCollector(settings, repository, station_cache)
reservation_manager = ReservationManager(
    station_cache.get_station,
    hold_seconds=settings.reservation_hold_minutes * 60,
    queue_ttl_seconds=settings.reservation_queue_ttl_minutes * 60,
    max_queue_per_station=settings.reservation_max_queue_per_station,
)
routing = RoutingService(
    settings.routing_mode,
    settings.osrm_base_url,
    settings.routing_algorithm,
)

tomtom_client = TomTomClient(
    settings.tomtom_api_key
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await collector.start()
    yield
    await collector.stop()


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(build_router(reservation_manager))


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": settings.app_name,
        "stations": len(station_cache.get_all_stations()),
        "tomtom_configured": bool(
            settings.tomtom_api_key
        ),
        "ocpi_configured": collector.ocpi.configured,
        "live_source": station_cache.live_source,
    }


@app.get("/api/stations")
async def stations():
    return {
        "stations": [
            station.model_dump()
            for station in station_cache.get_all_stations()
        ]
    }


@app.get("/api/data-status")
async def data_status():
    stations = station_cache.get_all_stations()
    return {
        "station_data": {
            "source": "coimbatore_csv" if any(
                station.source == "coimbatore_csv" for station in stations
            ) else "static",
            "last_updated": station_cache.station_last_updated,
            "station_count": len(stations),
            "verified_coordinate_count": sum(
                station.coordinate_verified for station in stations
            ),
        },
        "live_data": {
            "source": station_cache.live_source,
            "last_updated": station_cache.live_last_updated,
            "status": "available" if station_cache.live_source in {
                "OCPI", "TomTom"
            } else "fallback",
        },
        "routing": {
            "source": "OSRM when both endpoints are verified; otherwise estimate"
            if settings.routing_mode.lower() == "osrm"
            else "academic estimate",
            "verified_origin_count": len(verified_origins),
        },
        "queue_model": {"source": settings.queue_model},
    }


@app.get("/api/algorithms")
async def algorithms():
    """The ranking algorithms a request can choose with its `algorithm` field."""
    return {
        "default": "new_ranker",
        "algorithms": [
            {"id": key, "label": label, "group": group, "description": description}
            for key, (label, group, description) in ALGORITHMS.items()
        ],
    }


@dataclass
class Candidates:
    """Everything every algorithm needs, prepared once per request."""

    stations: list
    required_energy_kwh: float
    battery_urgency: str
    origin_latitude: float
    origin_longitude: float
    battery_capacity_kwh: float
    start_soc: float
    end_soc: float
    connector_status: dict
    reservation_counts: dict


async def prepare_candidates(request: RecommendationRequest) -> Candidates:
    verified_origin = verified_origins.get(request.origin_id or "")
    origin_latitude = (
        verified_origin["latitude"] if verified_origin else request.latitude
    )
    origin_longitude = (
        verified_origin["longitude"] if verified_origin else request.longitude
    )

    battery_capacity_kwh = (
        request.battery_capacity_kwh
        or settings.default_battery_capacity_kwh
    )

    if request.algorithm not in ALGORITHMS:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown algorithm '{request.algorithm}'. See GET /api/algorithms.",
        )

    if (
        request.target_battery_percent
        <= request.battery_percent
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                "Target battery percentage must "
                "be greater than current battery."
            ),
        )

    required_energy_kwh = (
        (
            request.target_battery_percent
            - request.battery_percent
        )
        / 100.0
        * battery_capacity_kwh
    )

    stations = station_cache.get_all_stations()

    remaining_energy_kwh = (
        battery_capacity_kwh
        * request.battery_percent
        / 100.0
    )
    estimated_range_km = (
        remaining_energy_kwh
        / request.consumption_kwh_per_km
    )
    if estimated_range_km < request.max_detour_km:
        battery_urgency = "CRITICAL"
    elif estimated_range_km < request.max_detour_km * 2:
        battery_urgency = "HIGH"
    elif estimated_range_km < request.max_detour_km * 4:
        battery_urgency = "MEDIUM"
    else:
        battery_urgency = "LOW"

    # Connector compatibility.
    stations, connector_status = filter_by_connector(
        stations,
        request.connector_type,
        include_unverified=settings.include_unverified_connectors,
    )

    # Spatial prefilter.
    stations = spatial_filter(
        stations,
        origin_latitude,
        origin_longitude,
        request.max_detour_km,
    )

    if stations and settings.routing_mode.lower() == "osrm":
        origin_is_verified = verified_origin is not None
        routable_stations = [
            station
            for station in stations
            if origin_is_verified and station.coordinate_verified
        ]
        routable_ids = {station.station_id for station in routable_stations}
        estimated_stations = [
            station for station in stations if station.station_id not in routable_ids
        ]
        apply_road_network_distance(
            estimated_stations,
            origin_latitude,
            origin_longitude,
        )
        route_results = await routing.route_many(
            origin_latitude,
            origin_longitude,
            routable_stations,
        )
        for station in routable_stations:
            route = route_results.get(station.station_id)
            if route is None:
                station.road_distance_km = None
                station.travel_time_min = None
                station.route_source = "osrm_unavailable"
                continue
            station.road_distance_km = route["distance_km"]
            station.travel_time_min = route["travel_time_min"]
            station.route_source = route["source"]
        stations = [
            station
            for station in stations
            if station.route_source != "OSRM"
            or (
                station.road_distance_km is not None
                and station.road_distance_km <= request.max_detour_km
            )
        ]

    # Other drivers' reservations: held ports are not free, queue slots add waiting.
    reservation_counts = reservation_manager.counts_for_ranking()
    stations = adjust_for_reservations(stations, reservation_counts)

    return Candidates(
        stations=stations,
        required_energy_kwh=required_energy_kwh,
        battery_urgency=battery_urgency,
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
        battery_capacity_kwh=battery_capacity_kwh,
        start_soc=request.battery_percent / 100.0,
        end_soc=request.target_battery_percent / 100.0,
        connector_status=connector_status,
        reservation_counts=reservation_counts,
    )


def recommendations_for(context: Candidates, algorithm: str):
    recommendations = run_algorithm(
        algorithm,
        context.stations,
        context.origin_latitude,
        context.origin_longitude,
        top_k=3,
        battery_urgency=context.battery_urgency,
        weights=settings.recommendation_weights,
        queue_model=settings.queue_model,
        battery_capacity_kwh=context.battery_capacity_kwh,
        start_soc=context.start_soc,
        end_soc=context.end_soc,
    )
    for recommendation in recommendations:
        recommendation.connector_compatibility = context.connector_status.get(
            recommendation.station_id,
            "unknown",
        )
        held, queued = context.reservation_counts.get(recommendation.station_id, (0, 0))
        recommendation.holds_applied = held
        recommendation.app_queue_length = queued
    return recommendations


@app.post(
    "/api/recommend",
    response_model=RecommendationResponse,
)
async def recommend(
    request: RecommendationRequest,
):
    context = await prepare_candidates(request)
    return RecommendationResponse(
        required_energy_kwh=round(context.required_energy_kwh, 2),
        recommendations=recommendations_for(context, request.algorithm),
        battery_urgency=context.battery_urgency,
        algorithm=request.algorithm,
        algorithm_label=ALGORITHMS[request.algorithm][0],
        data_status=await data_status(),
    )


@app.post(
    "/api/compare",
    response_model=CompareResponse,
)
async def compare(
    request: RecommendationRequest,
):
    """Run EVERY algorithm on the same request, so their choices can be compared."""
    context = await prepare_candidates(request)
    return CompareResponse(
        required_energy_kwh=round(context.required_energy_kwh, 2),
        battery_urgency=context.battery_urgency,
        cases=[
            AlgorithmCase(
                algorithm=key,
                label=label,
                group=group,
                description=description,
                recommendations=recommendations_for(context, key),
            )
            for key, (label, group, description) in ALGORITHMS.items()
        ],
    )
