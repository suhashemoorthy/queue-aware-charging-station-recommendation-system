from dataclasses import dataclass
from heapq import heappop, heappush
from math import atan2, cos, inf, radians, sin, sqrt
import re

from .config import get_settings


EARTH_RADIUS_KM = 6371.0


def normalize_connector(value: str) -> str:
    compact = re.sub(r"[^a-z0-9]", "", value.lower())
    if compact in {"ccs", "ccs2", "ccsii", "ccstype2"}:
        return "ccs2"
    if compact in {"type2", "actype2", "type2tetheredconnector"}:
        return "type2"
    if compact in {"chademo"}:
        return "chademo"
    return compact


def connectors_compatible(requested: str, available: list[str]) -> bool:
    requested_normalized = normalize_connector(requested)
    return any(
        normalize_connector(connector) == requested_normalized
        for connector in available
    )


def filter_by_connector(
    stations,
    requested: str,
    include_unverified: bool = True,
    allowed_statuses=frozenset({"operational", "available", "unknown"}),
):
    """Split stations by connector compatibility.

    Returns (candidates, status_by_station_id). Status is one of:
    "compatible", "incompatible", "unverified" (no connector listed) or "unavailable".
    Unverified stations stay in the candidate list when include_unverified is True,
    so a missing listing no longer hides almost half of the dataset.
    """
    candidates = []
    status: dict[str, str] = {}
    for station in stations:
        if station.status.lower() not in allowed_statuses:
            status[station.station_id] = "unavailable"
        elif not station.connector_types:
            status[station.station_id] = "unverified"
            if include_unverified:
                candidates.append(station)
        elif connectors_compatible(requested, station.connector_types):
            status[station.station_id] = "compatible"
            candidates.append(station)
        else:
            status[station.station_id] = "incompatible"
    return candidates, status


@dataclass(frozen=True)
class Edge:
    destination: str
    distance_km: float
    travel_time_min: float


# This is a study road graph, not live traffic data.
# The values should eventually be replaced by a routing provider
# or your verified academic graph dataset.
ROAD_GRAPH: dict[str, list[Edge]] = {
    "RS_PURAM": [
        Edge("GANDHIPURAM", 2.4, 8.0),
        Edge("SAIBABA_COLONY", 2.8, 9.0),
        Edge("RACE_COURSE", 2.5, 8.0),
    ],

    "GANDHIPURAM": [
        Edge("RS_PURAM", 2.4, 8.0),
        Edge("PEELAMEDU", 5.8, 17.0),
        Edge("RACE_COURSE", 2.3, 7.0),
    ],

    "PEELAMEDU": [
        Edge("GANDHIPURAM", 5.8, 17.0),
        Edge("AVINASHI_ROAD", 3.0, 9.0),
        Edge("SINGANALLUR", 4.0, 12.0),
        Edge("KALAPATTI", 5.8, 16.0),
    ],

    "AVINASHI_ROAD": [
        Edge("PEELAMEDU", 3.0, 9.0),
        Edge("SINGANALLUR", 4.5, 13.0),
    ],

    "SINGANALLUR": [
        Edge("AVINASHI_ROAD", 4.5, 13.0),
        Edge("PEELAMEDU", 4.0, 12.0),
    ],

    "RACE_COURSE": [
        Edge("RS_PURAM", 2.5, 8.0),
        Edge("GANDHIPURAM", 2.3, 7.0),
    ],

    "SAIBABA_COLONY": [
        Edge("RS_PURAM", 2.8, 9.0),
    ],

    "KALAPATTI": [
        Edge("PEELAMEDU", 5.8, 16.0),
    ],
}


NODE_COORDINATES = {
    "RS_PURAM": (11.0055, 76.9537),
    "GANDHIPURAM": (11.0168, 76.9558),
    "PEELAMEDU": (11.0301, 77.0007),
    "AVINASHI_ROAD": (11.0183, 77.0067),
    "SINGANALLUR": (10.9945, 77.0326),
    "RACE_COURSE": (10.9985, 76.9661),
    "SAIBABA_COLONY": (11.0242, 76.9344),
    "KALAPATTI": (11.0737, 77.0433),
}


STATION_NODE = {
    "CBE001": "RS_PURAM",
    "CBE002": "GANDHIPURAM",
    "CBE003": "PEELAMEDU",
    "CBE004": "AVINASHI_ROAD",
    "CBE005": "RACE_COURSE",
    "CBE006": "SINGANALLUR",
    "CBE007": "SAIBABA_COLONY",
    "CBE008": "KALAPATTI",
}


def haversine_distance(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> float:

    phi1 = radians(lat1)
    phi2 = radians(lat2)

    d_phi = radians(lat2 - lat1)
    d_lambda = radians(lon2 - lon1)

    a = (
        sin(d_phi / 2) ** 2
        + cos(phi1)
        * cos(phi2)
        * sin(d_lambda / 2) ** 2
    )

    return (
        2
        * EARTH_RADIUS_KM
        * atan2(
            sqrt(a),
            sqrt(1 - a),
        )
    )


def spatial_filter(
    stations,
    latitude: float,
    longitude: float,
    max_distance_km: float,
):
    candidates = []

    for station in stations:

        distance = haversine_distance(
            latitude,
            longitude,
            station.latitude,
            station.longitude,
        )

        if distance <= max_distance_km:

            station.road_distance_km = distance

            candidates.append(station)

    return candidates


def nearest_graph_node(
    latitude: float,
    longitude: float,
) -> str:

    return min(
        NODE_COORDINATES,
        key=lambda node: haversine_distance(
            latitude,
            longitude,
            NODE_COORDINATES[node][0],
            NODE_COORDINATES[node][1],
        ),
    )


def dijkstra(
    graph: dict[str, list[Edge]],
    source: str,
):
    """Shortest paths using a heap-based priority queue.

    Time complexity is O((V + E) log V); space complexity is O(V + E).
    """
    distances = {
        node: inf
        for node in graph
    }

    times = {
        node: inf
        for node in graph
    }

    previous = {
        node: None
        for node in graph
    }

    distances[source] = 0.0
    times[source] = 0.0

    queue = [(0.0, source)]

    while queue:

        current_distance, current = heappop(
            queue
        )

        if current_distance > distances[current]:
            continue

        for raw_edge in graph.get(current, []):
            edge = raw_edge
            if isinstance(raw_edge, tuple):
                edge = Edge(
                    destination=raw_edge[0],
                    distance_km=raw_edge[1],
                    travel_time_min=(
                        raw_edge[2] if len(raw_edge) > 2 else raw_edge[1]
                    ),
                )

            new_distance = (
                current_distance
                + edge.distance_km
            )

            if new_distance < distances[
                edge.destination
            ]:

                distances[
                    edge.destination
                ] = new_distance

                times[
                    edge.destination
                ] = (
                    times[current]
                    + edge.travel_time_min
                )

                previous[
                    edge.destination
                ] = current

                heappush(
                    queue,
                    (
                        new_distance,
                        edge.destination,
                    ),
                )

    return distances, times, previous


def astar(
    graph: dict[str, list[Edge]],
    source: str,
    target: str,
    heuristic=None,
):
    """A* shortest path with Haversine-compatible heuristic injection."""
    if heuristic is None:
        heuristic = lambda _node: 0.0

    distances = {node: inf for node in graph}
    times = {node: inf for node in graph}
    previous = {node: None for node in graph}
    distances[source] = 0.0
    times[source] = 0.0
    queue = [(heuristic(source), 0.0, source)]

    while queue:
        _, current_distance, current = heappop(queue)
        if current == target:
            break
        if current_distance > distances[current]:
            continue
        for raw_edge in graph.get(current, []):
            edge = raw_edge if not isinstance(raw_edge, tuple) else Edge(
                destination=raw_edge[0],
                distance_km=raw_edge[1],
                travel_time_min=raw_edge[2] if len(raw_edge) > 2 else raw_edge[1],
            )
            new_distance = current_distance + edge.distance_km
            if new_distance < distances[edge.destination]:
                distances[edge.destination] = new_distance
                times[edge.destination] = times[current] + edge.travel_time_min
                previous[edge.destination] = current
                heappush(
                    queue,
                    (new_distance + heuristic(edge.destination), new_distance, edge.destination),
                )
    return distances, times, previous


def apply_road_network_distance(
    stations,
    latitude: float,
    longitude: float,
):
    source = nearest_graph_node(
        latitude,
        longitude,
    )

    distances, times, _ = dijkstra(
        ROAD_GRAPH,
        source,
    )

    for station in stations:

        node = (
            STATION_NODE.get(station.station_id)
            if station.source != "coimbatore_csv"
            else None
        )

        if node:
            if node in distances and distances[node] < inf:
                station.road_distance_km = distances[node]
                station.travel_time_min = times[node]
                station.route_source = "academic_study_graph_estimate"
            continue

        # The supplied CSV has synthetic coordinates but no graph-node
        # identity. Use a clearly documented academic estimate rather than a
        # failed-route sentinel in the user-facing result.
        settings = get_settings()
        distance_km = settings.road_circuity_factor * haversine_distance(
            latitude,
            longitude,
            station.latitude,
            station.longitude,
        )
        station.road_distance_km = distance_km
        station.travel_time_min = (
            distance_km / settings.fallback_speed_kmh * 60.0
        )
        station.route_source = "haversine_estimate"

    return stations