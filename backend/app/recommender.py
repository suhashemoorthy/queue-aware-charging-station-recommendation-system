from heapq import nlargest
import logging
from statistics import median
from types import SimpleNamespace
from urllib.parse import quote

from .algorithms import apply_road_network_distance
from .charging_model import estimate_charge
from .config import get_settings
from .models import Recommendation
from .queue_model import estimate_wait_minutes

logger = logging.getLogger(__name__)

# Criteria the score is built from. The primary one is the total time the driver
# spends: travel + wait + charge, with the charge time computed from the power that
# actually reaches THIS battery (not the charger's rated kW).
DEFAULT_WEIGHTS = {
    "total_time": 0.55,
    "cost": 0.15,
    "availability": 0.10,
    "reliability": 0.15,
    "rating": 0.05,
}

BENEFIT_CRITERIA = {"availability", "reliability", "rating"}  # higher is better

# Extra weight when the battery is low. Weights are renormalised afterwards.
URGENCY_BOOST = {"total_time": 0.10, "availability": 0.05}


def _wait_estimate(station, queue_model: str) -> tuple[float, str]:
    if station.dynamic_data_source == "synthetic_demo_state":
        # A fully occupied station cannot have a zero wait: fall back to the
        # occupancy estimate when the simulated row says "no free port, no wait".
        if station.available_ports > 0 or station.estimated_wait_min > 0:
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


def normalize_weights(
    weights: dict[str, float],
    present: set[str],
    battery_urgency: str = "LOW",
) -> dict[str, float]:
    """Keep only criteria that have data, add the urgency boost, rescale to sum to 1."""
    used = {name: max(weights.get(name, 0.0), 0.0) for name in present}
    if battery_urgency in {"HIGH", "CRITICAL"}:
        for name, extra in URGENCY_BOOST.items():
            if name in used:
                used[name] += extra
    total = sum(used.values())
    if total <= 0:
        return {name: 1.0 / len(used) for name in used}
    return {name: value / total for name, value in used.items()}


def _lower_is_better(values: list[float]) -> list[float]:
    """Score = best value / this value, in (0, 1]; 1.0 is the best candidate.

    Ratio-to-best is used instead of min-max on purpose: min-max lets one very slow
    station stretch the range and squeeze the differences between the good options.
    """
    best = min(values)
    if best <= 0:
        return [1.0 for _ in values]
    return [best / value for value in values]


def _impute(values: list[float | None]) -> list[float]:
    """Fill individually missing values with the median of the known ones."""
    known = [value for value in values if value is not None]
    fill = median(known)
    return [fill if value is None else value for value in values]


def prepare_rows(
    stations,
    latitude: float,
    longitude: float,
    battery_kwh: float,
    start_soc: float = 0.1,
    end_soc: float = 0.8,
    queue_model: str | None = None,
):
    """Expected travel + wait + charge time and cost for THIS battery at every station.

    Every algorithm (the app's ranker and the alternatives) ranks the same rows, so any
    difference between them comes from the algorithm, not from the numbers it is given.
    """
    settings = get_settings()
    queue_model = queue_model or settings.queue_model

    # Route estimates (OSRM results are already attached by the API layer).
    osrm_attempt_failed = any(
        station.route_source == "osrm_unavailable"
        for station in stations
    )
    if (
        stations
        and not any(station.travel_time_min is not None for station in stations)
        and not osrm_attempt_failed
    ):
        stations = apply_road_network_distance(stations, latitude, longitude)

    # A missing route is an unavailable candidate, not a large travel time.
    stations = [
        station
        for station in stations
        if station.road_distance_km is not None
        and station.travel_time_min is not None
    ]

    rows = []
    for station in stations:
        if station.charging_speed_kw <= 0:
            logger.warning(
                "skipping %s: charger power unknown, cannot estimate charge time",
                station.station_id,
            )
            continue
        charge = estimate_charge(
            power_kw=station.charging_speed_kw,
            connector_class=station.connector_class,
            tariff_inr_per_kwh=station.cost_per_kwh,
            battery_kwh=battery_kwh,
            start_soc=start_soc,
            end_soc=end_soc,
        )
        wait_minutes, wait_source = _wait_estimate(station, queue_model)
        rows.append(
            SimpleNamespace(
                station=station,
                charge=charge,
                wait_minutes=wait_minutes,
                wait_source=wait_source,
                total_time=station.travel_time_min + wait_minutes + charge.minutes,
                session_cost=charge.cost_inr if station.cost_per_kwh > 0 else None,
                unverified=not station.connector_types,
            )
        )
    return rows


def make_reasons(row) -> list[str]:
    station = row.station
    reasons = []
    if station.available_ports > 0:
        reasons.append(f"{station.available_ports} ports currently available")
    else:
        reasons.append("No port currently available")
    if row.charge.delivered_kw >= 100:
        reasons.append("High-power fast charging")
    elif row.charge.delivered_kw >= 30:
        reasons.append("Fast charging for your battery")
    if station.travel_time_min <= 10:
        reasons.append("Low travel-time overhead")
    if (station.reliability_score or 0.0) >= 0.94:
        reasons.append("High reliability score")
    if station.live_data:
        reasons.append("Live availability")
    if row.unverified:
        reasons.append("Connector type not verified")
    return reasons


def build_recommendation(
    row,
    rank: int,
    battery_urgency: str,
    score: float | None = None,
    score_note: str | None = None,
    breakdown: dict[str, float] | None = None,
    algorithm: str = "new_ranker",
) -> Recommendation:
    station = row.station
    return Recommendation(
        rank=rank,
        algorithm=algorithm,
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
        score=None if score is None else round(score, 4),
        score_percent=None if score is None else round(score * 100, 1),
        score_note=score_note,
        road_distance_km=round(station.road_distance_km, 2),
        travel_time_min=round(station.travel_time_min, 1),
        available_ports=station.available_ports,
        total_ports=station.total_ports,
        queue_length=station.queue_length,
        charging_speed_kw=station.charging_speed_kw,
        cost_per_kwh=station.cost_per_kwh,
        connector_class=station.connector_class,
        rating=station.rating,
        reliability_score=station.reliability_score,
        estimated_wait_min=round(row.wait_minutes, 1),
        live_data=station.live_data,
        live_source=station.live_source,
        last_updated=station.live_last_updated,
        connector_compatibility="unverified" if row.unverified else "compatible",
        battery_urgency=battery_urgency,
        queue_model_source=row.wait_source,
        charge_time_min=row.charge.minutes,
        total_time_min=round(row.total_time, 1),
        session_cost_inr=row.session_cost,
        delivered_kw=row.charge.delivered_kw,
        vehicle_limit_kw=row.charge.vehicle_limit_kw,
        limited_by=row.charge.limited_by,
        score_breakdown={name: round(value, 4) for name, value in (breakdown or {}).items()},
        reasons=make_reasons(row),
        navigation_url=maps_url(station.name, station.address),
    )


def rank_candidates(
    stations,
    latitude: float,
    longitude: float,
    top_k: int = 3,
    battery_urgency: str = "LOW",
    weights: dict[str, float] | None = None,
    queue_model: str | None = None,
    battery_capacity_kwh: float | None = None,
    start_soc: float = 0.1,
    end_soc: float = 0.8,
) -> list[Recommendation]:
    """The app's own ranker ("new_ranker"): weighted score over expected total time,
    cost, availability, reliability and rating."""

    if not stations:
        return []

    settings = get_settings()
    battery_kwh = battery_capacity_kwh or settings.default_battery_capacity_kwh
    rows = prepare_rows(
        stations, latitude, longitude, battery_kwh, start_soc, end_soc, queue_model
    )
    if not rows:
        return []

    # Criterion scores (0..1, higher is better). Time and cost are relative to the
    # best candidate (ratio), the others are absolute.
    criteria: dict[str, list[float]] = {
        "total_time": _lower_is_better([row.total_time for row in rows]),
        "availability": [
            clamp(row.station.available_ports / max(row.station.total_ports, 1), 0, 1)
            for row in rows
        ],
    }
    costs = [row.session_cost for row in rows]
    if any(cost is not None for cost in costs):
        criteria["cost"] = _lower_is_better(_impute(costs))
    reliabilities = [row.station.reliability_score for row in rows]
    if any(value is not None for value in reliabilities):
        criteria["reliability"] = _impute(reliabilities)
    ratings = [row.station.rating if row.station.rating > 0 else None for row in rows]
    if any(value is not None for value in ratings):
        criteria["rating"] = [value / 5.0 for value in _impute(ratings)]

    score_weights = normalize_weights(
        weights or settings.recommendation_weights,
        set(criteria),
        battery_urgency,
    )

    for index, row in enumerate(rows):
        row.breakdown = {
            name: score_weights[name] * criteria[name][index]
            for name in criteria
        }
        row.score = sum(row.breakdown.values())
        if row.unverified:
            row.score *= settings.unverified_connector_penalty
        row.score = clamp(row.score, 0, 1)
        logger.info(
            "recommendation station=%s travel_min=%.1f wait_min=%.1f charge_min=%.1f "
            "total_min=%.1f availability=%d/%d cost_inr=%s delivered_kw=%.1f "
            "urgency=%s score=%.4f",
            row.station.station_id,
            row.station.travel_time_min,
            row.wait_minutes,
            row.charge.minutes,
            row.total_time,
            row.station.available_ports,
            row.station.total_ports,
            row.session_cost,
            row.charge.delivered_kw,
            battery_urgency,
            row.score,
        )

    # nlargest is stable: equal scores keep the input order; then shorter total time wins.
    top = nlargest(top_k, rows, key=lambda row: (row.score, -row.total_time))
    return [
        build_recommendation(
            row, rank, battery_urgency, score=row.score, breakdown=row.breakdown
        )
        for rank, row in enumerate(top, start=1)
    ]
