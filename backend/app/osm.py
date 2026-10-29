import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from .models import Station

logger = logging.getLogger(__name__)


class OSMError(Exception):
    pass


def _tag(tags: dict[str, Any], *names: str) -> str | None:
    for name in names:
        value = tags.get(name)
        if value not in (None, ""):
            return str(value)
    return None


def _float_tag(tags: dict[str, Any], *names: str) -> float:
    value = _tag(tags, *names)
    if not value:
        return 0.0
    try:
        return float(value.replace(",", ".").split()[0])
    except (ValueError, AttributeError):
        return 0.0


def _connectors(tags: dict[str, Any]) -> list[str]:
    value = _tag(tags, "socket:types", "socket:type2", "socket:ccs", "socket:chademo", "connector")
    if not value:
        return []
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def _coordinates(element: dict[str, Any]) -> tuple[float, float] | None:
    if element.get("lat") is not None and element.get("lon") is not None:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center") or {}
    if center.get("lat") is not None and center.get("lon") is not None:
        return float(center["lat"]), float(center["lon"])
    geometry = element.get("geometry") or []
    if geometry:
        lat = sum(point["lat"] for point in geometry) / len(geometry)
        lon = sum(point["lon"] for point in geometry) / len(geometry)
        return lat, lon
    return None


def osm_element_to_station(element: dict[str, Any]) -> Station | None:
    tags = element.get("tags") or {}
    coordinates = _coordinates(element)
    if coordinates is None:
        return None
    latitude, longitude = coordinates
    element_id = f"{element.get('type', 'element')}-{element.get('id')}"
    speed = _float_tag(tags, "charging_speed", "maxpower", "capacity:charging")
    capacity = int(_float_tag(tags, "capacity", "capacity:ports"))
    return Station(
        station_id=f"OSM-{element_id}",
        name=_tag(tags, "name", "brand") or "Unnamed charging station",
        latitude=latitude,
        longitude=longitude,
        operator=_tag(tags, "operator") or "Unknown",
        brand=_tag(tags, "brand"),
        connector_types=_connectors(tags),
        charging_speed_kw=speed,
        total_ports=capacity,
        available_ports=0,
        occupied_ports=0,
        cost_per_kwh=0,
        fee=_tag(tags, "fee"),
        opening_hours=_tag(tags, "opening_hours"),
        access=_tag(tags, "access"),
        source="OpenStreetMap",
        station_last_updated=datetime.now(timezone.utc),
        status="unknown",
    )


class OverpassClient:
    def __init__(self, url: str) -> None:
        self.url = url

    async def get_stations(self, area: str = "Coimbatore") -> list[Station]:
        query = f"""
        [out:json][timeout:30];
        area["name"="{area}"]["boundary"="administrative"]->.searchArea;
        (
          node["amenity"="charging_station"](area.searchArea);
          way["amenity"="charging_station"](area.searchArea);
          relation["amenity"="charging_station"](area.searchArea);
        );
        out center tags;
        """
        try:
            async with httpx.AsyncClient(timeout=35.0) as client:
                response = await client.post(self.url, data={"data": query})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OSMError("Overpass station request failed") from exc
        stations = [
            station
            for element in payload.get("elements", [])
            if (station := osm_element_to_station(element)) is not None
        ]
        logger.info("Loaded %d station records from OpenStreetMap", len(stations))
        return stations
