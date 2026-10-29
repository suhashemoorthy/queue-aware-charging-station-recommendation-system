from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "EV Charge Optimizer"

    tomtom_api_key: str | None = None

    ocpi_base_url: str | None = None
    ocpi_token: str | None = None
    ocpi_location_endpoint: str = "/locations"
    ocpi_status_endpoint: str = "/status"
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    routing_mode: str = "academic"
    routing_algorithm: str = "dijkstra"
    osrm_base_url: str | None = None
    station_refresh_seconds: int = 3600
    live_refresh_seconds: int = 180
    queue_model: str = "occupancy_estimate"
    historical_csv_path: str | None = None
    station_data_path: str | None = None
    verified_station_coordinates_path: str | None = None
    verified_origin_coordinates_path: str | None = None
    default_battery_capacity_kwh: float = 60.0
    enable_osm_refresh: bool = False

    # Ranking weights. They are renormalised at request time over the criteria that
    # actually have data (for example rating/reliability are dropped when no station
    # reports them), so they do not need to sum to 1 here.
    weight_total_time: float = 0.55   # travel + wait + charge, using delivered kW
    weight_cost: float = 0.15         # session cost in INR
    weight_availability: float = 0.10
    weight_reliability: float = 0.15
    weight_rating: float = 0.05

    # Stations that list no connector type are kept, flagged "unverified" and
    # multiplied by this factor, instead of being silently dropped.
    include_unverified_connectors: bool = True
    unverified_connector_penalty: float = 0.85

    # Reservation holds (in-memory, single process; see app/reservations.py)
    reservation_hold_minutes: float = 10.0        # how long a held port waits for the driver
    reservation_queue_ttl_minutes: float = 60.0   # how long a queue slot stays valid
    reservation_max_queue_per_station: int = 10

    # Fallback route estimate (used when OSRM is off or endpoints are unverified).
    # Straight-line distance is multiplied by the circuity factor (urban roads are
    # longer than the crow flies; 1.3 is a typical assumption, not a measurement).
    road_circuity_factor: float = 1.3
    fallback_speed_kmh: float = 30.0

    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5174,http://127.0.0.1:5174"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def allowed_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @property
    def recommendation_weights(self) -> dict[str, float]:
        return {
            "total_time": self.weight_total_time,
            "cost": self.weight_cost,
            "availability": self.weight_availability,
            "reliability": self.weight_reliability,
            "rating": self.weight_rating,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()