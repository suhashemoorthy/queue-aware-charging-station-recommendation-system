"""HTTP endpoints for reservations.

The handlers are plain `def` (not `async def`) on purpose: FastAPI runs them in a thread
pool, so requests really do run in parallel and the manager's lock is what keeps them
correct. (An `async def` handler would be serialised by the event loop and hide races.)
"""

from datetime import datetime, timezone
import re

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel, field_validator

from .reservations import ReservationError, ReservationManager

USER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


class ReservationRequest(BaseModel):
    station_id: str
    user_id: str  # opaque client-made id (no authentication in this prototype)

    @field_validator("user_id")
    @classmethod
    def valid_user_id(cls, value: str) -> str:
        if not USER_ID_PATTERN.match(value):
            raise ValueError("user_id must be 8-64 characters: letters, digits, - or _")
        return value


class ReservationOut(BaseModel):
    id: str
    station_id: str
    user_id: str
    status: str
    created_at: str
    expires_at: str | None
    seconds_remaining: int | None
    promoted_from_queue: bool
    queue_position: int | None
    cars_ahead: int | None
    estimated_wait_min: float | None
    replayed: bool = False
    promoted_reservation_ids: list[str] = []


def _iso(epoch: float | None) -> str | None:
    return None if epoch is None else datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _out(manager: ReservationManager, res, replayed=False, promoted=()) -> ReservationOut:
    view = manager.describe(res)
    view["created_at"] = _iso(view["created_at"])
    view["expires_at"] = _iso(view["expires_at"])
    return ReservationOut(**view, replayed=replayed, promoted_reservation_ids=[p.id for p in promoted])


def _http(error: ReservationError) -> HTTPException:
    return HTTPException(
        status_code=error.http_status,
        detail={"error": error.code, "message": error.message, **error.extra},
    )


def build_router(manager: ReservationManager) -> APIRouter:
    router = APIRouter(prefix="/api", tags=["reservations"])

    @router.delete("/reservations")
    def clear_reservations(request: Request):
        client_host = request.client.host if request.client else None
        if client_host not in {"127.0.0.1", "::1", "testclient"}:
            raise HTTPException(status_code=403, detail="Local access only.")
        return {"cleared": manager.clear()}

    @router.post("/reservations", response_model=ReservationOut, status_code=201)
    def reserve(
        body: ReservationRequest,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        """Take a port now. 201 on success, 409 station_full if none is free."""
        try:
            res, replayed = manager.reserve(body.station_id, body.user_id, idempotency_key)
        except ReservationError as error:
            raise _http(error)
        if replayed:
            response.status_code = 200
        return _out(manager, res, replayed)

    @router.post("/queue", response_model=ReservationOut, status_code=201)
    def join_queue(
        body: ReservationRequest,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        """Join the first-come queue of a full station."""
        try:
            res, replayed = manager.join_queue(body.station_id, body.user_id, idempotency_key)
        except ReservationError as error:
            raise _http(error)
        if replayed:
            response.status_code = 200
        return _out(manager, res, replayed)

    @router.get("/reservations/{reservation_id}", response_model=ReservationOut)
    def get_reservation(reservation_id: str):
        try:
            return _out(manager, manager.get(reservation_id))
        except ReservationError as error:
            raise _http(error)

    @router.post("/reservations/{reservation_id}/arrive", response_model=ReservationOut)
    def arrive(reservation_id: str):
        """The driver reached the station; the hold becomes a charging session."""
        try:
            return _out(manager, manager.arrive(reservation_id))
        except ReservationError as error:
            raise _http(error)

    @router.delete("/reservations/{reservation_id}", response_model=ReservationOut)
    def release(reservation_id: str):
        """Release a hold, leave the queue or finish a session. Safe to repeat."""
        try:
            res, promoted = manager.release(reservation_id)
        except ReservationError as error:
            raise _http(error)
        return _out(manager, res, promoted=promoted)

    @router.get("/stations/{station_id}/availability")
    def availability(station_id: str):
        """Availability after reservations: base ports, held, charging, queue, effective free."""
        try:
            return manager.station_view(station_id)
        except ReservationError as error:
            raise _http(error)

    return router
