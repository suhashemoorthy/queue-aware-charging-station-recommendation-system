import csv
import json
import re
from datetime import datetime
from pathlib import Path

from .models import Station


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "data" / "coimbatore_ev_stations_replica_demo_synthetic.csv"
VERIFIED_COORDINATES_FILE = BASE_DIR / "data" / "verified_station_coordinates.json"
VERIFIED_ORIGINS_FILE = BASE_DIR / "data" / "verified_origin_coordinates.json"

REQUIRED_CSV_COLUMNS = {
    "station_id", "station_name", "address", "connector_types",
    "source_name", "latitude", "longitude", "coordinate_source",
    "sim_total_ports", "sim_available_ports", "sim_occupied_ports",
    "sim_queue_length", "sim_estimated_wait_min", "sim_charging_power",
    "sim_price_inr_per_kwh", "sim_station_status", "simulation_timestamp",
    "dynamic_data_source",
}


def load_verified_origins(path: Path = VERIFIED_ORIGINS_FILE) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Verified origin coordinate sidecar contains invalid JSON") from exc
    if not isinstance(records, dict):
        raise RuntimeError("Verified origin coordinate sidecar must be a JSON object")

    origins = {}
    for origin_id, record in records.items():
        if not isinstance(record, dict):
            raise RuntimeError(f"Verified origin {origin_id} must be an object")
        try:
            latitude = float(record["latitude"])
            longitude = float(record["longitude"])
            source = str(record["source"]).strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Verified origin {origin_id} needs numeric latitude/longitude and source"
            ) from exc
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise RuntimeError(f"Verified origin {origin_id} coordinates are out of range")
        if not source.startswith("verified_"):
            raise RuntimeError(f"Coordinate source for {origin_id} must start with 'verified_'")
        origins[origin_id] = {
            "latitude": latitude,
            "longitude": longitude,
            "source": source,
        }
    return origins


def _required_text(row: dict[str, str], field: str, row_number: int) -> str:
    value = row.get(field, "").strip()
    if not value:
        raise ValueError(f"CSV row {row_number}: {field} cannot be empty")
    return value


def _number(row: dict[str, str], field: str, row_number: int) -> float:
    try:
        return float(row.get(field, "").strip())
    except ValueError as exc:
        raise ValueError(f"CSV row {row_number}: {field} must be numeric") from exc


def _power_kw(value: str, row_number: int) -> float:
    match = re.search(r"\d+(?:\.\d+)?", value)
    if not match:
        raise ValueError(f"CSV row {row_number}: sim_charging_power must contain a number")
    return float(match.group())


def _connectors(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[;,]", value) if item.strip()]


def _csv_station(row: dict[str, str], row_number: int) -> Station:
    station_id = _required_text(row, "station_id", row_number)
    name = _required_text(row, "station_name", row_number)
    latitude = _number(row, "latitude", row_number)
    longitude = _number(row, "longitude", row_number)
    total_ports = int(_number(row, "sim_total_ports", row_number))
    available_ports = int(_number(row, "sim_available_ports", row_number))
    occupied_ports = int(_number(row, "sim_occupied_ports", row_number))
    queue_length = int(_number(row, "sim_queue_length", row_number))
    estimated_wait_min = (
        _number(row, "sim_estimated_wait_min", row_number)
        if row.get("sim_estimated_wait_min", "").strip()
        else 0.0
    )
    cost_per_kwh = _number(row, "sim_price_inr_per_kwh", row_number)

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError(f"CSV row {row_number}: coordinates are out of range")
    if total_ports < 0 or available_ports < 0 or occupied_ports < 0:
        raise ValueError(f"CSV row {row_number}: port counts cannot be negative")
    if available_ports > total_ports or occupied_ports > total_ports:
        raise ValueError(f"CSV row {row_number}: port count exceeds total ports")
    if queue_length < 0 or estimated_wait_min < 0 or cost_per_kwh < 0:
        raise ValueError(f"CSV row {row_number}: queue, wait, and price cannot be negative")

    timestamp = datetime.fromisoformat(_required_text(row, "simulation_timestamp", row_number))
    source_name = _required_text(row, "source_name", row_number)
    dynamic_source = _required_text(row, "dynamic_data_source", row_number)

    return Station(
        station_id=station_id,
        name=name,
        address=row.get("address") or None,
        latitude=latitude,
        longitude=longitude,
        operator=row.get("listing_operator") or "Unknown",
        connector_types=_connectors(row.get("connector_types", "")),
        connector_class=(row.get("connector_class") or "UNKNOWN").strip().upper(),
        charging_speed_kw=_power_kw(row.get("sim_charging_power", ""), row_number),
        total_ports=total_ports,
        available_ports=available_ports,
        occupied_ports=occupied_ports,
        cost_per_kwh=cost_per_kwh,
        opening_hours=row.get("opening_hours") or None,
        source="coimbatore_csv",
        source_record_id=station_id,
        source_name=source_name,
        source_url=row.get("source_url") or None,
        coordinate_source=row.get("coordinate_source") or None,
        coordinate_note=row.get("coordinate_note") or None,
        station_last_updated=timestamp,
        status=_required_text(row, "sim_station_status", row_number),
        queue_length=queue_length,
        estimated_wait_min=estimated_wait_min,
        dynamic_data_source=dynamic_source,
        live_source=dynamic_source,
    )


class StationRepository:
    def __init__(
        self,
        path: Path = DATA_FILE,
        verified_coordinates_path: Path = VERIFIED_COORDINATES_FILE,
    ):
        self.path = path
        self.verified_coordinates_path = verified_coordinates_path

        if not self.path.exists():
            raise FileNotFoundError(
                f"Station dataset not found: {self.path}"
            )

        self._stations: list[Station] = []
        self._index: dict[str, Station] = {}

        self._load()

    def _load(self) -> None:
        if self.path.suffix.lower() == ".csv":
            stations = self._load_csv()
        else:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"{self.path.name} contains invalid JSON") from exc
            if not isinstance(raw, list):
                raise RuntimeError("Station dataset must be a JSON array")
            stations = [Station.model_validate(item) for item in raw]

        stations = self._apply_verified_coordinates(stations)
        ids = [
            station.station_id
            for station in stations
        ]

        if len(ids) != len(set(ids)):
            raise RuntimeError(
                "Duplicate station_id detected"
            )

        self._stations = stations

        # Hash table:
        # O(1) average station lookup by ID.
        self._index = {
            station.station_id: station
            for station in stations
        }

    def _apply_verified_coordinates(self, stations: list[Station]) -> list[Station]:
        if not self.verified_coordinates_path.exists():
            return stations

        try:
            coordinate_data = json.loads(
                self.verified_coordinates_path.read_text(encoding="utf-8")
            )
        except json.JSONDecodeError as exc:
            raise RuntimeError("Verified coordinate sidecar contains invalid JSON") from exc
        if not isinstance(coordinate_data, dict):
            raise RuntimeError("Verified coordinate sidecar must be a JSON object")

        stations_by_id = {station.station_id: station for station in stations}
        unknown_ids = set(coordinate_data) - set(stations_by_id)
        if unknown_ids:
            raise RuntimeError(
                f"Verified coordinates contain unknown station IDs: {sorted(unknown_ids)}"
            )

        for station_id, record in coordinate_data.items():
            if not isinstance(record, dict):
                raise RuntimeError(f"Verified coordinates for {station_id} must be an object")
            try:
                latitude = float(record["latitude"])
                longitude = float(record["longitude"])
                coordinate_source = str(record["source"]).strip()
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError(
                    f"Verified coordinates for {station_id} need numeric latitude/longitude and source"
                ) from exc
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise RuntimeError(f"Verified coordinates for {station_id} are out of range")
            if not coordinate_source.startswith("verified_"):
                raise RuntimeError(
                    f"Coordinate source for {station_id} must start with 'verified_'"
                )

            stations_by_id[station_id] = stations_by_id[station_id].model_copy(
                update={
                    "latitude": latitude,
                    "longitude": longitude,
                    "coordinate_source": coordinate_source,
                    "coordinate_note": record.get("note"),
                    "coordinate_verified": True,
                },
                deep=True,
            )

        return [stations_by_id[station.station_id] for station in stations]

    def _load_csv(self) -> list[Station]:
        with self.path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or [])
            missing = REQUIRED_CSV_COLUMNS - columns
            if missing:
                raise RuntimeError(f"CSV missing required columns: {sorted(missing)}")
            return [
                _csv_station(row, index)
                for index, row in enumerate(reader, start=2)
            ]

    def all(self) -> list[Station]:
        return [
            station.model_copy(deep=True)
            for station in self._stations
        ]

    def get(self, station_id: str) -> Station | None:
        station = self._index.get(station_id)

        if station is None:
            return None

        return station.model_copy(deep=True)