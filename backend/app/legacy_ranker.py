"""ORIGINAL ranking function, kept verbatim (only imports and the weights source adjusted)
so it can be compared with the new ranker (eval/compare_rankers.py) and chosen in the UI."""
from heapq import heappop, heappush
import logging
from urllib.parse import quote

from app.algorithms import (
    apply_road_network_distance,
    spatial_filter,
)
from app.config import get_settings
from app.models import Recommendation
from app.queue_model import estimate_wait_minutes

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {
    "distance": 0.10,
    "travel_time": 0.20,
    "availability": 0.20,
    "wait_time": 0.15,
    "charging_speed": 0.15,
    "cost": 0.05,
    "rating": 0.05,
    "reliability": 0.10,
}


def _wait_estimate(station, queue_model: str) -> tuple[float, str]:
    if station.dynamic_data_source == "synthetic_demo_state":
        return station.estimated_wait_min, station.dynamic_data_source
    return estimate_wait_minutes(
        station.available_ports,
        station.occupied_ports,
        station.reserved_ports,
        station.charging_speed_kw,
        queue_model,
    )


def clamp(
    value: float,
    minimum: float,
    maximum: float,
) -> float:

    return max(
        minimum,
        min(maximum, value),
    )


def inverse_normalize(
    value: float,
    minimum: float,
    maximum: float,
) -> float:

    if maximum <= minimum:
        return 1.0

    return 1.0 - (
        (value - minimum)
        / (maximum - minimum)
    )


def maps_url(
    station_name: str,
    address: str | None,
) -> str:

    destination_parts = [station_name]
    if address:
        destination_parts.append(address)
    if "coimbatore" not in " ".join(destination_parts).lower():
        destination_parts.append("Coimbatore, Tamil Nadu")
    destination = quote(
        ", ".join(destination_parts),
        safe="",
    )

    return (
        "https://www.google.com/maps/dir/"
        "?api=1"
        f"&destination={destination}"
        "&travelmode=driving"
    )


def rank_candidates(
    stations,
    latitude: float,
    longitude: float,
    top_k: int = 3,
    battery_urgency: str = "LOW",
    weights: dict[str, float] | None = None,
    queue_model: str | None = None,
) -> list[Recommendation]:

    if not stations:
        return []

    # ----------------------------------------------------
    # Road graph calculation.
    # ----------------------------------------------------

    osrm_attempt_failed = any(
        station.route_source == "osrm_unavailable"
        for station in stations
    )
    if (
        not any(station.travel_time_min is not None for station in stations)
        and not osrm_attempt_failed
    ):
        stations = apply_road_network_distance(stations, latitude, longitude)

    # ----------------------------------------------------
    # Do not rank failed routes. A missing route is an unavailable candidate,
    # not a large travel time that can leak into the result card.
    stations = [
        station
        for station in stations
        if station.road_distance_km is not None
        and station.travel_time_min is not None
    ]
    if not stations:
        return []

    max_distance = max(
        station.road_distance_km
        for station in stations
    )

    max_travel_time = max(
        station.travel_time_min
        for station in stations
    )

    max_speed = max(
        station.charging_speed_kw
        for station in stations
    )

    min_cost = min(
        station.cost_per_kwh
        for station in stations
    )

    max_cost = max(
        station.cost_per_kwh
        for station in stations
    )

    wait_values = [
        _wait_estimate(station, queue_model or get_settings().queue_model)[0]
        for station in stations
    ]
    max_wait = max(wait_values, default=0.0)
    score_weights = weights or DEFAULT_WEIGHTS
    if battery_urgency in {"HIGH", "CRITICAL"}:
        score_weights = {
            **score_weights,
            "travel_time": score_weights["travel_time"] + 0.05,
            "availability": score_weights["availability"] + 0.05,
            "distance": score_weights["distance"] + 0.02,
        }

    heap = []

    for station in stations:

        availability_ratio = (
            station.available_ports
            / max(
                station.total_ports,
                1,
            )
        )

        distance_score = inverse_normalize(
            station.road_distance_km,
            0,
            max_distance,
        )

        travel_score = inverse_normalize(
            station.travel_time_min,
            0,
            max_travel_time,
        )

        speed_score = (
            station.charging_speed_kw
            / max(
                max_speed,
                1,
            )
        )

        availability_score = clamp(
            availability_ratio,
            0,
            1,
        )

        cost_score = inverse_normalize(
            station.cost_per_kwh,
            min_cost,
            max_cost,
        )

        rating_score = (
            station.rating / 5.0
        )

        reliability_score = station.reliability_score or 0.0

        wait_minutes, wait_source = _wait_estimate(
            station,
            queue_model or get_settings().queue_model,
        )

        wait_score = inverse_normalize(
            wait_minutes,
            0,
            max_wait,
        )

        if max_distance == 0:
            distance_score = 1.0
        if max_travel_time == 0:
            travel_score = 1.0

        score = (
            score_weights["distance"]
            * distance_score

            + score_weights["travel_time"]
            * travel_score

            + score_weights["charging_speed"]
            * speed_score

            + score_weights["availability"]
            * availability_score

            + score_weights["cost"]
            * cost_score

            + score_weights["rating"]
            * rating_score

            + score_weights["reliability"]
            * reliability_score

            + score_weights["wait_time"]
            * wait_score
        )

        # Hard operational penalty.
        #
        # A station with no available ports can still be
        # recommended, but it should not beat a clearly
        # available station merely because it is nearby.
        if station.available_ports == 0:
            score *= 0.55

        score = clamp(
            score,
            0,
            1,
        )

        reasons = []

        if station.available_ports > 0:
            reasons.append(
                f"{station.available_ports} "
                f"ports currently available"
            )
        else:
            reasons.append(
                "No port currently available"
            )

        if station.charging_speed_kw >= 100:
            reasons.append(
                "High-power fast charging"
            )
        elif station.charging_speed_kw >= 60:
            reasons.append(
                "Fast charging capability"
            )

        if station.travel_time_min <= 10:
            reasons.append(
                "Low travel-time overhead"
            )

        if (station.reliability_score or 0.0) >= 0.94:
            reasons.append(
                "High reliability score"
            )

        if station.live_data:
            reasons.append(
                "Live availability"
            )

        item = (
            score,
            station.station_id,
            station,
            wait_minutes,
            reasons,
            wait_source,
        )

        if len(heap) < top_k:
            heappush(heap, item)

        elif score > heap[0][0]:
            heappop(heap)
            heappush(heap, item)

        logger.info(
            "recommendation station=%s distance_km=%.2f travel_time_min=%.1f "
            "availability=%d/%d wait_min=%.1f cost=%.2f "
            "rating=%.2f reliability=%.2f urgency=%s score=%.4f",
            station.station_id,
            station.road_distance_km,
            station.travel_time_min,
            station.available_ports,
            station.total_ports,
            wait_minutes,
            station.cost_per_kwh,
            station.rating,
            station.reliability_score or 0.0,
            battery_urgency,
            score,
        )

    results = []

    while heap:

        (
            score,
            _station_id,
            station,
            wait_minutes,
            reasons,
            wait_source,
        ) = heappop(heap)

        results.append(
            Recommendation(
                rank=0,

                station_id=station.station_id,
                name=station.name,
                operator=station.operator,
                address=station.address,
                source_name=station.source_name,
                coordinate_source=station.coordinate_source,
                coordinate_verified=station.coordinate_verified,
                dynamic_data_source=station.dynamic_data_source,
                route_source=station.route_source,

                latitude=station.latitude,
                longitude=station.longitude,

                score=round(score, 4),
                score_percent=round(
                    score * 100,
                    1,
                ),

                road_distance_km=round(
                    station.road_distance_km,
                    2,
                ),

                travel_time_min=round(
                    station.travel_time_min,
                    1,
                ),

                available_ports=(
                    station.available_ports
                ),

                total_ports=(
                    station.total_ports
                ),

                queue_length=station.queue_length,

                charging_speed_kw=(
                    station.charging_speed_kw
                ),

                cost_per_kwh=(
                    station.cost_per_kwh
                ),
                connector_class=station.connector_class,

                rating=station.rating,

                reliability_score=(
                    station.reliability_score
                ),

                estimated_wait_min=round(
                    wait_minutes,
                    1,
                ),

                live_data=station.live_data,

                live_source=station.live_source,
                last_updated=station.live_last_updated,
                connector_compatibility="compatible",
                battery_urgency=battery_urgency,
                queue_model_source=wait_source,

                reasons=reasons,

                navigation_url=maps_url(
                    station.name,
                    station.address,
                ),
            )
        )

    results.sort(
        key=lambda item: item.score,
        reverse=True,
    )

    for index, result in enumerate(
        results,
        start=1,
    ):
        result.rank = index

    return results