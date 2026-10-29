from datetime import datetime

from pydantic import BaseModel, Field, field_validator


class StationLiveState(BaseModel):
    station_id: str
    available_ports: int | None = Field(default=None, ge=0)
    occupied_ports: int | None = Field(default=None, ge=0)
    reserved_ports: int = Field(default=0, ge=0)
    out_of_service_ports: int = Field(default=0, ge=0)
    unknown_ports: int = Field(default=0, ge=0)
    status: str = "unknown"
    last_updated: datetime | None = None
    source: str = "static"


class Station(BaseModel):
    station_id: str
    name: str
    address: str | None = None

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)

    operator: str = "Unknown"
    brand: str | None = None
    source_record_id: str | None = None
    source_name: str = "static"
    source_url: str | None = None
    coordinate_source: str | None = None
    coordinate_note: str | None = None
    coordinate_verified: bool = False

    connector_types: list[str]
    connector_class: str = "UNKNOWN"

    charging_speed_kw: float = Field(default=0, ge=0)

    total_ports: int = Field(ge=0)
    available_ports: int = Field(ge=0)
    occupied_ports: int = Field(ge=0)

    reserved_ports: int = Field(default=0, ge=0)
    out_of_service_ports: int = Field(default=0, ge=0)

    cost_per_kwh: float = Field(default=0, ge=0)
    fee: str | None = None
    opening_hours: str | None = None
    access: str | None = None
    source: str = "static"
    station_last_updated: datetime | None = None

    rating: float = Field(default=0, ge=0, le=5)
    reliability_score: float | None = Field(default=None, ge=0, le=1)

    # TomTom chargingAvailability identifier.
    # It can be null for stations that have no dynamic integration.
    charging_availability_id: str | None = None

    live_data: bool = False
    live_source: str = "static"
    live_last_updated: datetime | None = None
    unknown_ports: int = Field(default=0, ge=0)
    status: str = "unknown"
    queue_length: int = Field(default=0, ge=0)
    estimated_wait_min: float = Field(default=0, ge=0)
    dynamic_data_source: str = "static"

    road_distance_km: float | None = None
    travel_time_min: float | None = None
    route_source: str = "unavailable"


class RecommendationRequest(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    origin_coordinate_source: str = "unverified"
    origin_id: str | None = None

    battery_percent: float = Field(ge=0, le=100)

    battery_capacity_kwh: float | None = Field(
        default=None,
        gt=0,
        le=500,
    )
    consumption_kwh_per_km: float = Field(
        default=0.18,
        gt=0,
        le=5,
    )

    target_battery_percent: float = Field(
        ge=0,
        le=100,
    )

    max_detour_km: float = Field(
        gt=0,
        le=100,
    )

    connector_type: str = "CCS2"
    # which ranking algorithm decides the order (see GET /api/algorithms)
    algorithm: str = "new_ranker"

    @field_validator("connector_type")
    @classmethod
    def validate_connector_type(cls, value: str) -> str:
        value = value.strip()

        if not value:
            raise ValueError(
                "connector_type cannot be empty"
            )

        return value


class Recommendation(BaseModel):
    rank: int

    station_id: str
    name: str
    operator: str = "Unknown"
    address: str | None = None
    source_name: str = "static"
    coordinate_source: str | None = None
    coordinate_verified: bool = False
    dynamic_data_source: str = "static"
    route_source: str = "unavailable"

    latitude: float
    longitude: float

    # Only scoring algorithms have a score; rule-based ones (nearest, cheapest...) leave
    # these empty and describe their rule in score_note instead.
    score: float | None = None
    score_percent: float | None = None
    score_note: str | None = None
    algorithm: str = "new_ranker"

    road_distance_km: float
    travel_time_min: float

    available_ports: int
    total_ports: int
    queue_length: int

    charging_speed_kw: float
    cost_per_kwh: float
    connector_class: str = "UNKNOWN"

    rating: float
    reliability_score: float | None

    estimated_wait_min: float

    live_data: bool
    live_source: str = "static"
    last_updated: datetime | None = None
    connector_compatibility: str = "compatible"
    battery_urgency: str = "LOW"
    queue_model_source: str = "occupancy_estimate"

    # Charging estimate for the user's own battery (single source of truth).
    charge_time_min: float = 0.0
    total_time_min: float = 0.0        # travel + wait + charge
    session_cost_inr: float | None = None
    delivered_kw: float = 0.0          # power actually reaching the battery
    vehicle_limit_kw: float = 0.0      # what the battery can accept (auto-derived)
    limited_by: str = "charger"        # "battery" or "charger"
    score_breakdown: dict[str, float] = Field(default_factory=dict)

    # Reservations already taken at this station by other drivers (already reflected
    # in available_ports, queue_length and estimated_wait_min above).
    holds_applied: int = 0
    app_queue_length: int = 0

    reasons: list[str]

    navigation_url: str


class RecommendationResponse(BaseModel):
    required_energy_kwh: float
    recommendations: list[Recommendation]
    battery_urgency: str = "LOW"
    algorithm: str = "new_ranker"
    algorithm_label: str = ""
    data_status: dict[str, object] = Field(default_factory=dict)


class AlgorithmCase(BaseModel):
    algorithm: str
    label: str
    group: str
    description: str
    recommendations: list[Recommendation]


class CompareResponse(BaseModel):
    required_energy_kwh: float
    battery_urgency: str
    cases: list[AlgorithmCase]