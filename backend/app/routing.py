import logging
from typing import Any

import httpx

from .algorithms import (
    NODE_COORDINATES,
    ROAD_GRAPH,
    STATION_NODE,
    apply_road_network_distance,
    astar,
    haversine_distance,
    nearest_graph_node,
)
from .config import get_settings
from .models import Station

logger = logging.getLogger(__name__)


class RoutingService:
    def __init__(self, mode: str = "academic", osrm_base_url: str | None = None, algorithm: str = "dijkstra") -> None:
        self.mode = mode.lower()
        self.osrm_base_url = osrm_base_url.rstrip("/") if osrm_base_url else None
        self.algorithm = algorithm.lower()

    async def route_many(
        self,
        latitude: float,
        longitude: float,
        stations: list[Station],
    ) -> dict[str, dict[str, Any]]:
        if self.mode != "osrm" or not self.osrm_base_url or not stations:
            return {}

        coordinates = [f"{longitude},{latitude}"] + [
            f"{station.longitude},{station.latitude}"
            for station in stations
        ]
        url = (
            f"{self.osrm_base_url}/table/v1/driving/"
            + ";".join(coordinates)
        )
        params = {
            "sources": "0",
            "destinations": ";".join(
                str(index) for index in range(1, len(coordinates))
            ),
            "annotations": "distance,duration",
        }

        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
            distances = payload["distances"][0]
            durations = payload["durations"][0]
            if payload.get("code") != "Ok":
                raise ValueError("OSRM table response was not successful")
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning("OSRM route table failed: %s", exc)
            return {}

        results = {}
        for station, distance_m, duration_s in zip(stations, distances, durations):
            if distance_m is None or duration_s is None:
                continue
            results[station.station_id] = {
                "distance_km": distance_m / 1000.0,
                "travel_time_min": duration_s / 60.0,
                "source": "OSRM",
            }
        return results

    async def route(self, latitude: float, longitude: float, station: Station) -> dict[str, Any]:
        if self.mode == "osrm" and self.osrm_base_url:
            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    coordinates = f"{longitude},{latitude};{station.longitude},{station.latitude}"
                    response = await client.get(f"{self.osrm_base_url}/route/v1/driving/{coordinates}", params={"overview": "false"})
                    response.raise_for_status()
                    route = response.json()["routes"][0]
                    return {"distance_km": route["distance"] / 1000, "travel_time_min": route["duration"] / 60, "source": "OSRM"}
            except (httpx.HTTPError, KeyError, IndexError, ValueError) as exc:
                logger.warning("OSRM route failed for %s: %s", station.station_id, exc)
        if self.algorithm == "astar":
            source = nearest_graph_node(latitude, longitude)
            target = STATION_NODE.get(station.station_id)
            if target:
                distances, times, _ = astar(
                    ROAD_GRAPH,
                    source,
                    target,
                    heuristic=lambda node: haversine_distance(
                        NODE_COORDINATES[node][0],
                        NODE_COORDINATES[node][1],
                        NODE_COORDINATES[target][0],
                        NODE_COORDINATES[target][1],
                    ),
                )
                if distances[target] != float("inf"):
                    station.road_distance_km = distances[target]
                    station.travel_time_min = times[target]
        else:
            apply_road_network_distance([station], latitude, longitude)
        if station.road_distance_km is None:
            settings = get_settings()
            station.road_distance_km = settings.road_circuity_factor * haversine_distance(
                latitude,
                longitude,
                station.latitude,
                station.longitude,
            )
            station.travel_time_min = (
                station.road_distance_km
                / settings.fallback_speed_kmh
                * 60
            )
            source = "haversine"
        else:
            source = "academic"
        return {
            "distance_km": station.road_distance_km,
            "travel_time_min": station.travel_time_min,
            "source": source,
        }
