"""Reservation holds and a FIFO queue per station.

Why this exists: recommendations alone change nothing, so concurrent drivers who see the
same "1 / 1 ports" result all drive to the same station. A reservation takes a port in
one atomic step, so exactly one of N simultaneous requests wins; the others get a clear
"station_full" answer and can join the queue or pick another station.

Design
  * One re-entrant lock guards all reservation state. Every public method takes it, so
    "check that a port is free" and "take it" can never interleave (no race).
  * Holds do not edit the station cache. They are subtracted when availability is read:
        effective_free = station.available_ports - active holds
    so expiring a hold simply makes the port visible again.
  * A hold expires after `hold_seconds`. Expiry is evaluated on every call (lazy sweep),
    so no background thread is needed and the behaviour is easy to test with a fake clock.
  * Queue order is a server-side sequence number (first come, first served), never a
    client timestamp. When a port frees up the head of the queue is promoted to a hold.
  * Retrying a request with the same Idempotency-Key returns the same reservation.
  * One active reservation per user (stops one user hoarding ports).

Limits (read before relying on it)
  * State is in memory in ONE process. With several workers each would have its own
    counts; swap the dicts for Redis/a database (the public methods are the interface).
  * There is no authentication: user_id is an opaque id the client makes up.
  * Cars queued at the station by external drivers are not tracked: they only enter the
    wait estimate through the station's own queue_length.
"""

from __future__ import annotations

import itertools
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from .models import Station
from .queue_model import queue_wait_minutes, typical_session_minutes

OPERATIONAL_STATUSES = {"operational", "available", "unknown"}
RETENTION_SECONDS = 3600  # finished reservations stay readable for an hour


class Status(str, Enum):
    HELD = "HELD"            # port reserved, driver has not arrived yet
    QUEUED = "QUEUED"        # waiting in line for a port
    CHARGING = "CHARGING"    # driver arrived, port in use
    COMPLETED = "COMPLETED"  # finished charging
    CANCELLED = "CANCELLED"  # released before charging
    EXPIRED = "EXPIRED"      # hold or queue slot timed out


ACTIVE = {Status.HELD, Status.QUEUED, Status.CHARGING}


class ReservationError(Exception):
    """A refused request. `code` is machine readable, `extra` is returned to the client."""

    def __init__(self, code: str, message: str, http_status: int = 409, **extra):
        super().__init__(message)
        self.code, self.message, self.http_status, self.extra = code, message, http_status, extra


@dataclass
class Reservation:
    id: str
    user_id: str
    station_id: str
    status: Status
    seq: int
    created_at: float
    updated_at: float
    expires_at: float | None = None
    promoted_from_queue: bool = False


class ReservationManager:
    def __init__(
        self,
        station_lookup: Callable[[str], Station | None],
        hold_seconds: float = 600.0,
        queue_ttl_seconds: float = 3600.0,
        max_queue_per_station: int = 10,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._lookup = station_lookup
        self._hold_seconds = hold_seconds
        self._queue_ttl_seconds = queue_ttl_seconds
        self._max_queue = max_queue_per_station
        self._clock = clock

        self._lock = threading.RLock()
        self._reservations: dict[str, Reservation] = {}
        self._active_by_user: dict[str, str] = {}
        self._active_by_station: dict[str, set[str]] = {}
        self._queues: dict[str, deque[str]] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, str, str]] = {}
        self._seq = itertools.count(1)
        self._ids = itertools.count(1)

    # ------------------------------------------------------------------ public API
    def reserve(self, station_id: str, user_id: str, idempotency_key: str | None = None):
        """Take a port now, atomically. Raises ReservationError if none is free."""
        with self._lock:
            now = self._begin()
            replay = self._replay(user_id, idempotency_key, "reserve", station_id)
            if replay:
                return replay, True
            self._refuse_if_user_busy(user_id)
            station = self._station(station_id)
            self._require_operational(station)
            if self._effective_free(station) <= 0:
                raise ReservationError(
                    "station_full",
                    "No port is free at this station right now.",
                    can_queue=True,
                    queue_length=station.queue_length + len(self._queue(station_id)),
                    estimated_wait_min=self._wait_for(station, len(self._queue(station_id))),
                )
            res = self._create(station_id, user_id, Status.HELD, now, now + self._hold_seconds)
            self._remember(user_id, idempotency_key, "reserve", station_id, res.id)
            return res, False

    def join_queue(self, station_id: str, user_id: str, idempotency_key: str | None = None):
        """Join the first-come queue of a station that has no free port."""
        with self._lock:
            now = self._begin()
            replay = self._replay(user_id, idempotency_key, "queue", station_id)
            if replay:
                return replay, True
            self._refuse_if_user_busy(user_id)
            station = self._station(station_id)
            self._require_operational(station)
            if self._effective_free(station) > 0:
                raise ReservationError(
                    "port_available",
                    "A port is free: reserve it instead of queueing.",
                )
            if len(self._queue(station_id)) >= self._max_queue:
                raise ReservationError("queue_full", "The queue at this station is full.")
            res = self._create(station_id, user_id, Status.QUEUED, now, now + self._queue_ttl_seconds)
            self._queue(station_id).append(res.id)
            self._remember(user_id, idempotency_key, "queue", station_id, res.id)
            return res, False

    def get(self, reservation_id: str) -> Reservation:
        with self._lock:
            self._begin()
            return self._find(reservation_id)

    def arrive(self, reservation_id: str) -> Reservation:
        """The driver reached the station: the held port becomes an active session."""
        with self._lock:
            now = self._begin()
            res = self._find(reservation_id)
            if res.status == Status.EXPIRED:
                raise ReservationError("hold_expired", "The hold expired before you arrived.")
            if res.status != Status.HELD:
                raise ReservationError(
                    "invalid_state", f"Cannot arrive from state {res.status.value}.",
                    status=res.status.value,
                )
            res.status, res.expires_at, res.updated_at = Status.CHARGING, None, now
            return res

    def release(self, reservation_id: str) -> tuple[Reservation, list[Reservation]]:
        """Give the port or queue slot back. Safe to call twice. Returns (reservation, promoted)."""
        with self._lock:
            now = self._begin()
            res = self._find(reservation_id)
            if res.status not in ACTIVE:
                return res, []
            final = Status.COMPLETED if res.status == Status.CHARGING else Status.CANCELLED
            self._finish(res, final, now)
            return res, self._promote(res.station_id, now)

    def clear(self) -> int:
        """Remove all reservation history and active state; return the number removed."""
        with self._lock:
            count = len(self._reservations)
            self._reservations.clear()
            self._active_by_user.clear()
            self._active_by_station.clear()
            self._queues.clear()
            self._idempotency.clear()
            return count

    def station_view(self, station_id: str) -> dict:
        with self._lock:
            self._begin()
            station = self._station(station_id)
            held, charging = self._count(station_id, Status.HELD), self._count(station_id, Status.CHARGING)
            return {
                "station_id": station_id,
                "base_available_ports": station.available_ports,
                "held": held,
                "charging": charging,
                "effective_free": self._effective_free(station),
                "app_queue_length": len(self._queue(station_id)),
                "station_queue_length": station.queue_length,
            }

    def counts_for_ranking(self) -> dict[str, tuple[int, int]]:
        """{station_id: (ports blocked by reservations, app queue length)} for stations
        that have any reservation activity. One lock hold, so the snapshot is consistent."""
        with self._lock:
            self._begin()
            out = {}
            for station_id in list(self._active_by_station):
                station = self._lookup(station_id)
                if station is None:
                    continue
                blocked = self._blocked(station)
                queued = len(self._queue(station_id))
                if blocked or queued:
                    out[station_id] = (blocked, queued)
            return out

    def describe(self, res: Reservation) -> dict:
        """Plain-dict view of a reservation, including queue position and wait."""
        with self._lock:
            now = self._clock()
            view = {
                "id": res.id,
                "station_id": res.station_id,
                "user_id": res.user_id,
                "status": res.status.value,
                "created_at": res.created_at,
                "expires_at": res.expires_at,
                "seconds_remaining": (
                    max(int(res.expires_at - now), 0)
                    if res.expires_at is not None and res.status in {Status.HELD, Status.QUEUED}
                    else None
                ),
                "promoted_from_queue": res.promoted_from_queue,
                "queue_position": None,
                "cars_ahead": None,
                "estimated_wait_min": None,
            }
            if res.status == Status.QUEUED:
                station = self._lookup(res.station_id)
                queue = self._queue(res.station_id)
                index = list(queue).index(res.id) if res.id in queue else 0
                view["queue_position"] = index + 1
                if station is not None:
                    ahead = station.queue_length + index
                    view["cars_ahead"] = ahead
                    view["estimated_wait_min"] = round(self._wait_for(station, index), 1)
            return view

    # ------------------------------------------------------------------- internals
    # Everything below assumes self._lock is held.
    def _begin(self) -> float:
        now = self._clock()
        self._sweep(now)
        return now

    def _station(self, station_id: str) -> Station:
        station = self._lookup(station_id)
        if station is None:
            raise ReservationError("station_not_found", "Unknown station.", http_status=404)
        return station

    @staticmethod
    def _require_operational(station: Station) -> None:
        if station.status.lower() not in OPERATIONAL_STATUSES:
            raise ReservationError("station_unavailable", "This station is not operational.")

    def _find(self, reservation_id: str) -> Reservation:
        res = self._reservations.get(reservation_id)
        if res is None:
            raise ReservationError("reservation_not_found", "Unknown reservation.", http_status=404)
        return res

    def _queue(self, station_id: str) -> deque:
        return self._queues.setdefault(station_id, deque())

    def _count(self, station_id: str, status: Status) -> int:
        return sum(
            1 for rid in self._active_by_station.get(station_id, ())
            if self._reservations[rid].status == status
        )

    def _blocked(self, station: Station) -> int:
        """Ports taken away from the station's own count by our reservations.
        Live feeds already report cars that are charging, so those are not subtracted."""
        held = self._count(station.station_id, Status.HELD)
        charging = 0 if station.live_data else self._count(station.station_id, Status.CHARGING)
        return held + charging

    def _effective_free(self, station: Station) -> int:
        if station.status.lower() not in OPERATIONAL_STATUSES:
            return 0
        return max(station.available_ports - self._blocked(station), 0)

    def _wait_for(self, station: Station, app_cars_ahead: int) -> float:
        ports = max(station.total_ports - station.out_of_service_ports, 1)
        return queue_wait_minutes(station.queue_length + app_cars_ahead, ports, station.charging_speed_kw)

    def _create(self, station_id, user_id, status, now, expires_at) -> Reservation:
        res = Reservation(
            id=f"r{next(self._ids):06d}", user_id=user_id, station_id=station_id, status=status,
            seq=next(self._seq), created_at=now, updated_at=now, expires_at=expires_at,
        )
        self._reservations[res.id] = res
        self._active_by_user[user_id] = res.id
        self._active_by_station.setdefault(station_id, set()).add(res.id)
        return res

    def _finish(self, res: Reservation, status: Status, now: float) -> None:
        if res.status == Status.QUEUED:
            queue = self._queue(res.station_id)
            if res.id in queue:
                queue.remove(res.id)
        res.status, res.updated_at, res.expires_at = status, now, None
        if self._active_by_user.get(res.user_id) == res.id:
            del self._active_by_user[res.user_id]
        self._active_by_station.get(res.station_id, set()).discard(res.id)

    def _promote(self, station_id: str, now: float) -> list[Reservation]:
        """Hand freed ports to the head of the queue, in order."""
        promoted = []
        station = self._lookup(station_id)
        queue = self._queue(station_id)
        while station is not None and queue and self._effective_free(station) > 0:
            res = self._reservations[queue.popleft()]
            res.status, res.promoted_from_queue = Status.HELD, True
            res.expires_at, res.updated_at = now + self._hold_seconds, now
            promoted.append(res)
        return promoted

    def _sweep(self, now: float) -> None:
        touched = set(self._queues)  # live availability may have changed: re-check queues
        for res in list(self._reservations.values()):
            if res.status in {Status.HELD, Status.QUEUED} and res.expires_at is not None \
                    and res.expires_at <= now:
                touched.add(res.station_id)
                self._finish(res, Status.EXPIRED, now)
        for station_id in touched:
            self._promote(station_id, now)
        self._prune(now)

    def _prune(self, now: float) -> None:
        stale = [
            rid for rid, res in self._reservations.items()
            if res.status not in ACTIVE and now - res.updated_at > RETENTION_SECONDS
        ]
        for rid in stale:
            del self._reservations[rid]
        if stale:
            for key, (_, _, rid) in list(self._idempotency.items()):
                if rid not in self._reservations:
                    del self._idempotency[key]

    def _refuse_if_user_busy(self, user_id: str) -> None:
        existing = self._active_by_user.get(user_id)
        if existing is not None:
            res = self._reservations[existing]
            raise ReservationError(
                "user_has_active_reservation",
                "Release your current reservation before taking another.",
                reservation_id=res.id, station_id=res.station_id, status=res.status.value,
            )

    def _replay(self, user_id, key, kind, station_id):
        if not key:
            return None
        known = self._idempotency.get((user_id, key))
        if known is None:
            return None
        known_kind, known_station, rid = known
        if known_kind != kind or known_station != station_id:
            raise ReservationError(
                "idempotency_key_reuse",
                "This Idempotency-Key was already used for a different request.",
                http_status=422,
            )
        return self._reservations.get(rid)

    def _remember(self, user_id, key, kind, station_id, rid) -> None:
        if key:
            self._idempotency[(user_id, key)] = (kind, station_id, rid)


def adjust_for_reservations(stations: list[Station], counts: dict[str, tuple[int, int]]) -> list[Station]:
    """Return stations as they look AFTER other drivers' reservations, for ranking.

    Held ports are removed from availability; reserved queue slots lengthen the queue.
    Stations without reservation activity are returned unchanged (same objects).
    """
    adjusted = []
    for station in stations:
        blocked, app_queue = counts.get(station.station_id, (0, 0))
        if not blocked and not app_queue:
            adjusted.append(station)
            continue
        available = max(station.available_ports - blocked, 0)
        ports = max(station.total_ports - station.out_of_service_ports, 1)
        queue = station.queue_length + app_queue
        wait = station.estimated_wait_min
        if available == 0 and station.available_ports > 0:
            wait = queue_wait_minutes(queue, ports, station.charging_speed_kw)  # just filled up
        elif available == 0:
            # already full: every reserved queue slot adds one session, shared by all ports
            wait += app_queue * typical_session_minutes(station.charging_speed_kw) / ports
        adjusted.append(station.model_copy(update={
            "available_ports": available,
            "occupied_ports": station.occupied_ports + (station.available_ports - available),
            "queue_length": queue,
            "estimated_wait_min": round(wait, 1),
        }))
    return adjusted
