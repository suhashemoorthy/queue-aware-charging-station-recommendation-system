"""Fire many drivers at a RUNNING server at the same moment and show what happens.

    python -m uvicorn app.main:app --port 8000        (in one terminal)
    python scripts/concurrent_drivers_demo.py --drivers 20

Each driver asks for recommendations, then tries to reserve the best station; if it is
full they try the next one, and finally join the queue. Nothing is ever oversold.
"""

import argparse
import collections
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx

REQUEST = {
    "latitude": 11.0301, "longitude": 77.0007, "origin_id": "PEELAMEDU",
    "origin_coordinate_source": "study_graph_estimate",
    "battery_percent": 27, "target_battery_percent": 80, "battery_capacity_kwh": 60,
    "max_detour_km": 10, "connector_type": "CCS2",
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drivers", type=int, default=20)
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    barrier = threading.Barrier(args.drivers)

    def driver(index):
        user_id = f"demo-{uuid.uuid4().hex[:12]}"
        with httpx.Client(base_url=args.base, timeout=15) as client:
            barrier.wait()                                   # everyone starts together
            top = client.post("/api/recommend", json=REQUEST).json()["recommendations"]
            first_choice = top[0]["station_id"]
            for rec in top:                                   # try best first, then fall back
                r = client.post("/api/reservations", json={"station_id": rec["station_id"], "user_id": user_id})
                if r.status_code == 201:
                    return first_choice, rec["station_id"], "reserved"
            r = client.post("/api/queue", json={"station_id": first_choice, "user_id": user_id})
            return first_choice, first_choice, "queued" if r.status_code == 201 else f"failed({r.status_code})"

    with ThreadPoolExecutor(args.drivers) as pool:
        results = list(pool.map(driver, range(args.drivers)))

    print(f"{args.drivers} drivers asked at the same moment.")
    print("First choice of every driver:", dict(collections.Counter(r[0] for r in results)))
    print("Where they ended up        :", dict(collections.Counter((r[1], r[2]) for r in results)))
    with httpx.Client(base_url=args.base) as client:
        for station_id in sorted({r[1] for r in results}):
            print(" ", station_id, client.get(f"/api/stations/{station_id}/availability").json())


if __name__ == "__main__":
    main()
