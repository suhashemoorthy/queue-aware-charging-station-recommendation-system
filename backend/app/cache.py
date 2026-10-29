from datetime import datetime, timezone
from threading import RLock

from .models import Station, StationLiveState


class StationCache:
    """In-memory station store; its interface can later back onto Redis."""

    def __init__(self) -> None:
        self._stations: dict[str, Station] = {}
        self._lock = RLock()
        self.station_last_updated: datetime | None = None
        self.live_last_updated: datetime | None = None
        self.live_source = "static"

    def set_station(self, station: Station) -> None:
        with self._lock:
            self._stations[station.station_id] = station.model_copy(deep=True)
            self.station_last_updated = datetime.now(timezone.utc)

    def set_stations(self, stations: list[Station]) -> None:
        with self._lock:
            self._stations = {
                station.station_id: station.model_copy(deep=True)
                for station in stations
            }
            self.station_last_updated = datetime.now(timezone.utc)

    def get_station(self, station_id: str) -> Station | None:
        with self._lock:
            station = self._stations.get(station_id)
            return station.model_copy(deep=True) if station else None

    def get_all_stations(self) -> list[Station]:
        with self._lock:
            return [station.model_copy(deep=True) for station in self._stations.values()]

    def update_live_state(self, state: StationLiveState) -> Station | None:
        with self._lock:
            station = self._stations.get(state.station_id)
            if station is None:
                return None
            if state.available_ports is not None:
                station.available_ports = state.available_ports
            if state.occupied_ports is not None:
                station.occupied_ports = state.occupied_ports
            station.reserved_ports = state.reserved_ports
            station.out_of_service_ports = state.out_of_service_ports
            station.unknown_ports = state.unknown_ports
            station.status = state.status
            station.live_source = state.source
            station.live_data = state.source in {"OCPI", "TomTom"}
            station.live_last_updated = state.last_updated
            self.live_last_updated = state.last_updated
            self.live_source = state.source
            return station.model_copy(deep=True)
