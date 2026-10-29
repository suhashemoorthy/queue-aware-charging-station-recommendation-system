from app.algorithms import astar, dijkstra
from app.models import Station
from app.recommender import rank_candidates


def station(
    station_id: str,
    latitude: float,
    longitude: float,
    available: int,
    total: int,
    speed: float,
) -> Station:

    return Station(
        station_id=station_id,
        name=f"Test {station_id}",
        latitude=latitude,
        longitude=longitude,
        operator="TEST",
        connector_types=["CCS2"],
        charging_speed_kw=speed,
        total_ports=total,
        available_ports=available,
        occupied_ports=total - available,
        cost_per_kwh=18,
        rating=4.5,
        reliability_score=0.95,
    )


def test_dijkstra_shortest_path():

    graph = {
        "A": [
            type(
                "Edge",
                (),
                {
                    "destination": "B",
                    "distance_km": 2,
                    "travel_time_min": 5,
                },
            )()
        ],
        "B": [
            type(
                "Edge",
                (),
                {
                    "destination": "C",
                    "distance_km": 3,
                    "travel_time_min": 7,
                },
            )()
        ],
        "C": [],
    }

    distances, times, _ = dijkstra(
        graph,
        "A",
    )

    assert distances["C"] == 5
    assert times["C"] == 12


def test_astar_supports_tuple_adjacency_list():
    graph = {
        "A": [("B", 2, 5)],
        "B": [("C", 3, 7)],
        "C": [],
    }
    distances, times, _ = astar(graph, "A", "C")
    assert distances["C"] == 5
    assert times["C"] == 12


def test_available_station_can_outscore_busy_station():

    busy = station(
        "BUSY",
        11.0055,
        76.9537,
        available=0,
        total=4,
        speed=60,
    )

    available = station(
        "AVAILABLE",
        11.0168,
        76.9558,
        available=4,
        total=4,
        speed=120,
    )

    result = rank_candidates(
        [busy, available],
        latitude=11.0100,
        longitude=76.9550,
        top_k=2,
    )

    assert result
    assert result[0].station_id == "AVAILABLE"


def test_top_k_is_limited():

    stations = [
        station(
            f"S{i}",
            11.0055 + i * 0.002,
            76.9537 + i * 0.002,
            available=2,
            total=4,
            speed=60,
        )
        for i in range(6)
    ]

    result = rank_candidates(
        stations,
        latitude=11.0100,
        longitude=76.9550,
        top_k=3,
    )

    assert len(result) <= 3


