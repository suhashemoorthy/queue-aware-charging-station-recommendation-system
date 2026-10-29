import logging
from datetime import datetime
from typing import Any

import httpx

from .models import Station, StationLiveState

logger = logging.getLogger(__name__)


class OCPIError(Exception):
    pass


STATUS_MAP = {
    "AVAILABLE": "available",
    "CHARGING": "occupied",
    "OCCUPIED": "occupied",
    "RESERVED": "reserved",
    "OUTOFORDER": "out_of_service",
    "OUT_OF_ORDER": "out_of_service",
    "INOPERATIVE": "out_of_service",
}


def normalize_ocpi_status(payload: dict[str, Any]) -> StationLiveState:
    station_id = str(payload.get("station_id") or payload.get("location_id") or payload.get("evse_uid"))
    status = str(payload.get("status") or "UNKNOWN").upper()
    mapped = STATUS_MAP.get(status, "unknown")
    counts = {"available_ports": 0, "occupied_ports": 0, "reserved_ports": 0, "out_of_service_ports": 0, "unknown_ports": 0}
    counts[f"{mapped}_ports"] = 1 if mapped != "unknown" else 0
    if mapped == "unknown":
        counts["unknown_ports"] = 1
    updated = payload.get("last_updated")
    return StationLiveState(
        station_id=station_id,
        status=mapped,
        last_updated=datetime.fromisoformat(updated.replace("Z", "+00:00")) if isinstance(updated, str) else None,
        source="OCPI",
        **counts,
    )


def normalize_ocpi_location(payload: dict[str, Any]) -> Station | None:
    coordinates = payload.get("coordinates") or {}
    if coordinates.get("latitude") is None or coordinates.get("longitude") is None:
        return None
    evses = payload.get("evses") or []
    connectors = [str(connector.get("standard")) for evse in evses for connector in evse.get("connectors", []) if connector.get("standard")]
    powers = [float(connector.get("power", 0) or 0) for evse in evses for connector in evse.get("connectors", [])]
    return Station(
        station_id=str(payload.get("id")),
        name=payload.get("name") or "Unnamed OCPI station",
        latitude=float(coordinates["latitude"]), longitude=float(coordinates["longitude"]),
        operator=payload.get("operator", {}).get("name", "Unknown") if isinstance(payload.get("operator"), dict) else str(payload.get("operator") or "Unknown"),
        connector_types=connectors,
        charging_speed_kw=max(powers, default=0),
        total_ports=len(evses), available_ports=0, occupied_ports=0,
        cost_per_kwh=0, source="OCPI", status="unknown",
    )


class OCPIClient:
    def __init__(self, base_url: str | None, token: str | None, location_endpoint: str, status_endpoint: str) -> None:
        self.base_url = base_url.rstrip("/") if base_url else None
        self.token = token
        self.location_endpoint = location_endpoint
        self.status_endpoint = status_endpoint

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.token)

    async def _get(self, endpoint: str) -> Any:
        if not self.configured:
            raise OCPIError("OCPI is not configured")
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                response = await client.get(f"{self.base_url}/{endpoint.lstrip('/')}", headers={"Authorization": f"Token {self.token}"})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OCPIError("OCPI request failed") from exc
        return payload.get("data", payload)

    async def get_locations(self) -> list[Station]:
        payload = await self._get(self.location_endpoint)
        return [station for item in payload if (station := normalize_ocpi_location(item)) is not None]

    async def get_evse_status(self) -> list[StationLiveState]:
        payload = await self._get(self.status_endpoint)
        return [normalize_ocpi_status(item) for item in payload]
