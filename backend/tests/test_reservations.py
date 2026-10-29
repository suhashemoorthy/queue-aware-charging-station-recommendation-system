"""Reservation tests: logic with a fake clock, then genuinely parallel requests."""

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models import Station
from app.reservations import (
    ReservationError,
    ReservationManager,
    Status,
    adjust_for_reservations,
)
from app.routes_reservations import build_router


# --------------------------------------------------------------------------- helpers
def station(station_id="S1", available=1, total=1, queue=0, wait=0.0, status="operational",
            live=False, power=50.0) -> Station:
    return Station(
        station_id=station_id, name=f"Station {station_id}", latitude=11.0, longitude=77.0,
        connector_types=["CCS2"], charging_speed_kw=power, cost_per_kwh=18.0,
        total_ports=total, available_ports=available, occupied_ports=total - available,
        queue_length=queue, estimated_wait_min=wait, status=status, live_data=live,
    )


class FakeClock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def make_manager(stations, clock=None, **kwargs):
    table = {s.station_id: s for s in stations}
    return ReservationManager(lambda sid: table.get(sid), clock=clock or FakeClock(), **kwargs)


def user(n):
    return f"user-{n:04d}-abcd"


def error_code(callable_, *args, **kwargs):
    with pytest.raises(ReservationError) as info:
        callable_(*args, **kwargs)
    return info.value.code


# ------------------------------------------------------------------------- the basics
def test_reserve_takes_the_last_port_and_the_next_driver_is_refused():
    manager = make_manager([station(available=1)])
    res, replayed = manager.reserve("S1", user(1))
    assert res.status == Status.HELD and not replayed
    assert manager.station_view("S1")["effective_free"] == 0
    assert error_code(manager.reserve, "S1", user(2)) == "station_full"


def test_refusal_tells_the_driver_they_can_queue_and_how_long():
    manager = make_manager([station(available=0, total=1, queue=2)])
    with pytest.raises(ReservationError) as info:
        manager.reserve("S1", user(1))
    assert info.value.extra["can_queue"] is True
    assert info.value.extra["queue_length"] == 2
    assert info.value.extra["estimated_wait_min"] > 0


def test_unknown_and_non_operational_stations_are_refused():
    manager = make_manager([station("DOWN", status="temporarily_unavailable")])
    assert error_code(manager.reserve, "NOPE", user(1)) == "station_not_found"
    assert error_code(manager.reserve, "DOWN", user(1)) == "station_unavailable"
    assert error_code(manager.join_queue, "DOWN", user(1)) == "station_unavailable"


def test_one_active_reservation_per_user():
    manager = make_manager([station("A", available=1), station("B", available=1)])
    manager.reserve("A", user(1))
    assert error_code(manager.reserve, "B", user(1)) == "user_has_active_reservation"


def test_hold_expires_and_the_port_comes_back():
    clock = FakeClock()
    manager = make_manager([station(available=1)], clock, hold_seconds=600)
    res, _ = manager.reserve("S1", user(1))
    clock.advance(599)
    assert manager.get(res.id).status == Status.HELD
    clock.advance(2)
    assert manager.get(res.id).status == Status.EXPIRED
    assert manager.station_view("S1")["effective_free"] == 1
    manager.reserve("S1", user(2))  # now possible, and user 1 may book again too


def test_arrive_turns_a_hold_into_a_session_that_does_not_expire():
    clock = FakeClock()
    manager = make_manager([station(available=1)], clock, hold_seconds=600)
    res, _ = manager.reserve("S1", user(1))
    manager.arrive(res.id)
    clock.advance(10_000)
    assert manager.get(res.id).status == Status.CHARGING
    assert manager.station_view("S1")["effective_free"] == 0


def test_arrive_after_expiry_is_refused():
    clock = FakeClock()
    manager = make_manager([station(available=1)], clock, hold_seconds=60)
    res, _ = manager.reserve("S1", user(1))
    clock.advance(61)
    assert error_code(manager.arrive, res.id) == "hold_expired"


def test_release_is_idempotent_and_frees_the_port():
    manager = make_manager([station(available=1)])
    res, _ = manager.reserve("S1", user(1))
    first, _ = manager.release(res.id)
    again, promoted = manager.release(res.id)
    assert first.status == again.status == Status.CANCELLED and promoted == []
    assert manager.station_view("S1")["effective_free"] == 1


def test_local_clear_endpoint_removes_reservation_and_queue_state():
    manager = make_manager([station(available=1)])
    holder, _ = manager.reserve("S1", user(1))
    manager.join_queue("S1", user(2))
    app = FastAPI()
    app.include_router(build_router(manager))

    with TestClient(app) as client:
        response = client.delete("/api/reservations")

    assert response.status_code == 200
    assert response.json() == {"cleared": 2}
    assert manager.station_view("S1")["effective_free"] == 1
    assert manager.station_view("S1")["app_queue_length"] == 0
    assert error_code(manager.get, holder.id) == "reservation_not_found"


def test_finishing_a_session_marks_it_completed():
    manager = make_manager([station(available=1)])
    res, _ = manager.reserve("S1", user(1))
    manager.arrive(res.id)
    done, _ = manager.release(res.id)
    assert done.status == Status.COMPLETED


# ---------------------------------------------------------------------------- queueing
def test_cannot_queue_while_a_port_is_free():
    manager = make_manager([station(available=1)])
    assert error_code(manager.join_queue, "S1", user(1)) == "port_available"


def test_queue_is_first_come_first_served_and_head_is_promoted_on_release():
    manager = make_manager([station(available=1)])
    holder, _ = manager.reserve("S1", user(0))
    q1, _ = manager.join_queue("S1", user(1))
    q2, _ = manager.join_queue("S1", user(2))
    q3, _ = manager.join_queue("S1", user(3))
    assert [manager.describe(r)["queue_position"] for r in (q1, q2, q3)] == [1, 2, 3]

    _, promoted = manager.release(holder.id)
    assert [p.id for p in promoted] == [q1.id]           # exactly one port freed, one promoted
    assert manager.get(q1.id).status == Status.HELD
    assert manager.get(q1.id).promoted_from_queue
    assert manager.describe(manager.get(q2.id))["queue_position"] == 1  # moved up
    assert manager.get(q3.id).status == Status.QUEUED


def test_leaving_the_queue_moves_everyone_behind_up_without_touching_ports():
    manager = make_manager([station(available=1)])
    manager.reserve("S1", user(0))
    q1, _ = manager.join_queue("S1", user(1))
    q2, _ = manager.join_queue("S1", user(2))
    _, promoted = manager.release(q1.id)
    assert promoted == []
    assert manager.describe(manager.get(q2.id))["queue_position"] == 1


def test_expired_hold_promotes_the_next_in_line():
    clock = FakeClock()
    manager = make_manager([station(available=1)], clock, hold_seconds=600)
    holder, _ = manager.reserve("S1", user(0))
    waiting, _ = manager.join_queue("S1", user(1))
    clock.advance(601)
    assert manager.get(holder.id).status == Status.EXPIRED
    assert manager.get(waiting.id).status == Status.HELD


def test_queue_wait_includes_cars_already_at_the_station():
    manager = make_manager([station(available=0, total=1, queue=3)])
    res, _ = manager.join_queue("S1", user(1))
    view = manager.describe(res)
    assert view["cars_ahead"] == 3 and view["queue_position"] == 1
    assert view["estimated_wait_min"] > 0


def test_queue_has_a_size_limit_and_queue_slots_expire():
    clock = FakeClock()
    manager = make_manager([station(available=0)], clock, max_queue_per_station=2, queue_ttl_seconds=100)
    first, _ = manager.join_queue("S1", user(1))
    manager.join_queue("S1", user(2))
    assert error_code(manager.join_queue, "S1", user(3)) == "queue_full"
    clock.advance(101)
    assert manager.get(first.id).status == Status.EXPIRED


# ------------------------------------------------------------------------ idempotency
def test_same_idempotency_key_returns_the_same_reservation():
    manager = make_manager([station(available=2, total=2)])
    first, replay1 = manager.reserve("S1", user(1), "key-1")
    second, replay2 = manager.reserve("S1", user(1), "key-1")
    assert first.id == second.id and not replay1 and replay2
    assert manager.station_view("S1")["held"] == 1


def test_idempotency_key_cannot_be_reused_for_another_request():
    manager = make_manager([station("A", available=1), station("B", available=1)])
    manager.reserve("A", user(1), "key-1")
    with pytest.raises(ReservationError) as info:
        manager.reserve("B", user(1), "key-1")
    assert info.value.code == "idempotency_key_reuse" and info.value.http_status == 422


# ----------------------------------------------------- availability seen by the ranker
def test_live_stations_do_not_double_count_charging_cars():
    synthetic = make_manager([station(available=2, total=2)])
    live = make_manager([station(available=2, total=2, live=True)])
    for manager in (synthetic, live):
        res, _ = manager.reserve("S1", user(1))
        manager.arrive(res.id)
    assert synthetic.station_view("S1")["effective_free"] == 1   # our car is not in the feed
    assert live.station_view("S1")["effective_free"] == 2        # the feed already shows it


def test_ranking_sees_held_ports_as_taken_and_queue_as_longer():
    base = station(available=1, total=1, wait=0.0)
    manager = make_manager([base])
    manager.reserve("S1", user(1))
    adjusted = adjust_for_reservations([base], manager.counts_for_ranking())[0]
    assert adjusted.available_ports == 0 and adjusted.occupied_ports == 1
    assert adjusted.estimated_wait_min > 0
    manager.join_queue("S1", user(2))
    queued = adjust_for_reservations([base], manager.counts_for_ranking())[0]
    assert queued.queue_length == 1 and queued.estimated_wait_min > adjusted.estimated_wait_min
    assert base.available_ports == 1  # the cache object itself is never edited


def test_stations_without_reservations_are_returned_unchanged():
    base = station()
    assert adjust_for_reservations([base], {})[0] is base


# =========================================================== PARALLEL REQUESTS (manager)
def run_parallel(count, work):
    """Start `count` threads together behind a barrier so they really collide."""
    barrier = threading.Barrier(count)

    def task(index):
        barrier.wait()
        return work(index)

    with ThreadPoolExecutor(max_workers=count) as pool:
        return list(pool.map(task, range(count)))


def outcome(manager_call, *args):
    try:
        manager_call(*args)
        return "ok"
    except ReservationError as error:
        return error.code


@pytest.mark.parametrize("free_ports", [1, 3])
def test_parallel_reserve_exactly_as_many_succeed_as_there_are_free_ports(free_ports):
    manager = make_manager([station(available=free_ports, total=free_ports)])
    results = run_parallel(100, lambda i: outcome(manager.reserve, "S1", user(i)))
    assert results.count("ok") == free_ports
    assert results.count("station_full") == 100 - free_ports
    view = manager.station_view("S1")
    assert view["held"] == free_ports and view["effective_free"] == 0


def test_parallel_reserve_with_the_same_idempotency_key_creates_one_reservation():
    manager = make_manager([station(available=5, total=5)])
    ids = run_parallel(50, lambda i: manager.reserve("S1", user(1), "same-key")[0].id)
    assert len(set(ids)) == 1
    assert manager.station_view("S1")["held"] == 1


def test_parallel_queue_joins_get_unique_consecutive_positions():
    manager = make_manager([station(available=0, total=1)], max_queue_per_station=100)
    reservations = run_parallel(60, lambda i: manager.join_queue("S1", user(i))[0])
    positions = sorted(manager.describe(r)["queue_position"] for r in reservations)
    assert positions == list(range(1, 61))


def test_parallel_reserve_and_release_never_oversell_a_port():
    manager = make_manager([station(available=2, total=2)])
    violations = []

    def work(i):
        for _ in range(30):
            try:
                res, _ = manager.reserve("S1", user(i))
            except ReservationError:
                continue
            view = manager.station_view("S1")
            if view["held"] > 2 or view["effective_free"] < 0:
                violations.append(view)
            manager.release(res.id)

    run_parallel(20, work)
    assert violations == []
    assert manager.station_view("S1") ["held"] == 0


# ====================================================== PARALLEL REQUESTS (real HTTP server)
@pytest.fixture()
def live_server():
    """A real uvicorn server in a thread, so requests arrive over sockets in parallel."""
    table = {"ONE": station("ONE", available=1, total=1), "THREE": station("THREE", available=3, total=3)}
    manager = ReservationManager(lambda sid: table.get(sid), max_queue_per_station=100)
    app = FastAPI()
    app.include_router(build_router(manager))

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "test server did not start"
    yield f"http://127.0.0.1:{port}", manager
    server.should_exit = True
    thread.join(timeout=5)


def http_post(base, path, payload, headers=None):
    with httpx.Client(timeout=10) as client:
        return client.post(base + path, json=payload, headers=headers or {})


def test_http_40_simultaneous_requests_for_one_free_port_exactly_one_succeeds(live_server):
    base, manager = live_server
    responses = run_parallel(
        40, lambda i: http_post(base, "/api/reservations", {"station_id": "ONE", "user_id": user(i)})
    )
    codes = [r.status_code for r in responses]
    assert codes.count(201) == 1
    assert codes.count(409) == 39
    assert all(r.json()["detail"]["error"] == "station_full" for r in responses if r.status_code == 409)
    assert manager.station_view("ONE")["held"] == 1


def test_http_three_free_ports_three_winners(live_server):
    base, _ = live_server
    responses = run_parallel(
        30, lambda i: http_post(base, "/api/reservations", {"station_id": "THREE", "user_id": user(i)})
    )
    assert [r.status_code for r in responses].count(201) == 3


def test_http_full_flow_reserve_queue_release_promote(live_server):
    base, manager = live_server
    winner = http_post(base, "/api/reservations", {"station_id": "ONE", "user_id": user(0)})
    assert winner.status_code == 201 and winner.json()["status"] == "HELD"

    queued = run_parallel(
        10, lambda i: http_post(base, "/api/queue", {"station_id": "ONE", "user_id": user(i + 1)})
    )
    assert all(r.status_code == 201 for r in queued)
    assert sorted(r.json()["queue_position"] for r in queued) == list(range(1, 11))
    first_in_line = next(r.json() for r in queued if r.json()["queue_position"] == 1)

    with httpx.Client(timeout=10) as client:
        released = client.delete(f"{base}/api/reservations/{winner.json()['id']}")
        assert released.status_code == 200
        assert released.json()["status"] == "CANCELLED"
        assert released.json()["promoted_reservation_ids"] == [first_in_line["id"]]
        promoted = client.get(f"{base}/api/reservations/{first_in_line['id']}").json()
        assert promoted["status"] == "HELD" and promoted["promoted_from_queue"] is True
        availability = client.get(f"{base}/api/stations/ONE/availability").json()
        assert availability["held"] == 1 and availability["app_queue_length"] == 9


def test_http_retry_with_idempotency_key_is_safe_under_parallel_load(live_server):
    base, manager = live_server
    responses = run_parallel(
        25,
        lambda i: http_post(
            base, "/api/reservations", {"station_id": "THREE", "user_id": user(7)},
            headers={"Idempotency-Key": "retry-me"},
        ),
    )
    assert {r.status_code for r in responses} <= {200, 201}
    assert len({r.json()["id"] for r in responses}) == 1
    assert manager.station_view("THREE")["held"] == 1


# ------------------------------------------------------------- validation (TestClient)
def test_api_validation_and_error_shapes():
    table = {"ONE": station("ONE", available=1, total=1)}
    manager = ReservationManager(lambda sid: table.get(sid))
    app = FastAPI()
    app.include_router(build_router(manager))
    client = TestClient(app)

    assert client.post("/api/reservations", json={"station_id": "ONE", "user_id": "short"}).status_code == 422
    missing = client.post("/api/reservations", json={"station_id": "NOPE", "user_id": user(1)})
    assert missing.status_code == 404 and missing.json()["detail"]["error"] == "station_not_found"
    assert client.get("/api/reservations/r999999").status_code == 404
    assert client.get("/api/stations/NOPE/availability").status_code == 404
