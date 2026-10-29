from typing import Any

import httpx

from .models import Station


class TomTomError(Exception):
    pass


class TomTomClient:
    BASE_URL = (
        "https://api.tomtom.com/"
        "search/2/chargingAvailability.json"
    )

    def __init__(self, api_key: str | None):
        self.api_key = api_key

    async def get_availability(
        self,
        station: Station,
    ) -> dict[str, Any] | None:

        if not self.api_key:
            return None

        if not station.charging_availability_id:
            return None

        params = {
            "key": self.api_key,
            "chargingAvailability":
                station.charging_availability_id,
        }

        try:
            async with httpx.AsyncClient(
                timeout=8.0
            ) as client:

                response = await client.get(
                    self.BASE_URL,
                    params=params,
                    headers={
                        "Tracking-ID":
                            f"ev-{station.station_id}"
                    },
                )

                response.raise_for_status()

                return response.json()

        except httpx.TimeoutException as exc:
            raise TomTomError(
                "TomTom request timed out"
            ) from exc

        except httpx.HTTPStatusError as exc:
            raise TomTomError(
                f"TomTom returned HTTP "
                f"{exc.response.status_code}"
            ) from exc

        except ValueError as exc:
            raise TomTomError(
                "TomTom returned invalid JSON"
            ) from exc


def parse_availability(
    data: dict[str, Any],
) -> dict[str, int]:

    available = 0
    occupied = 0
    reserved = 0
    unknown = 0
    out_of_service = 0

    connectors = data.get(
        "connectors",
        []
    )

    if not isinstance(connectors, list):
        raise TomTomError(
            "Invalid TomTom connectors payload"
        )

    for connector in connectors:

        if not isinstance(connector, dict):
            continue

        current = (
            connector
            .get("availability", {})
            .get("current", {})
        )

        if not isinstance(current, dict):
            continue

        available += int(
            current.get("available", 0) or 0
        )

        occupied += int(
            current.get("occupied", 0) or 0
        )

        reserved += int(
            current.get("reserved", 0) or 0
        )

        unknown += int(
            current.get("unknown", 0) or 0
        )

        out_of_service += int(
            current.get("outOfService", 0) or 0
        )

    return {
        "available_ports": available,
        "occupied_ports": occupied,
        "reserved_ports": reserved,
        "unknown_ports": unknown,
        "out_of_service_ports": out_of_service,
    }


async def update_station_from_tomtom(
    station: Station,
    client: TomTomClient,
) -> Station:

    try:
        data = await client.get_availability(
            station
        )

        if not data:
            return station

        state = parse_availability(data)

        station.available_ports = state[
            "available_ports"
        ]

        station.occupied_ports = state[
            "occupied_ports"
        ]

        station.reserved_ports = state[
            "reserved_ports"
        ]

        station.out_of_service_ports = state[
            "out_of_service_ports"
        ]

        station.live_data = True

        return station

    except TomTomError:
        # Fail closed to the last known/static state.
        # Do not destroy an otherwise usable recommendation.
        station.live_data = False
        return station