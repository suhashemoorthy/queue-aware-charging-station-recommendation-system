import logging
from datetime import datetime, timezone

from .cache import StationCache
from .models import Station
from .ocpi import OCPIClient, OCPIError
from .tomtom import TomTomClient, TomTomError, parse_availability

logger = logging.getLogger(__name__)


async def refresh_live_data(
    stations: list[Station],
    cache: StationCache,
    ocpi: OCPIClient,
    tomtom: TomTomClient,
) -> str:
    """Apply OCPI, then TomTom, then retain static/previous state."""
    if ocpi.configured:
        try:
            states = await ocpi.get_evse_status()
            for state in states:
                cache.update_live_state(state)
            if states:
                logger.info("Live availability refreshed from OCPI")
                return "OCPI"
        except OCPIError as exc:
            logger.warning("OCPI unavailable; trying TomTom: %s", exc)

    if tomtom.api_key:
        updated = 0
        for station in stations:
            if not station.charging_availability_id:
                continue
            try:
                payload = await tomtom.get_availability(station)
                if payload:
                    values = parse_availability(payload)
                    station.available_ports = values["available_ports"]
                    station.occupied_ports = values["occupied_ports"]
                    station.reserved_ports = values["reserved_ports"]
                    station.out_of_service_ports = values["out_of_service_ports"]
                    station.unknown_ports = values["unknown_ports"]
                    station.live_data = True
                    station.live_source = "TomTom"
                    station.live_last_updated = datetime.now(timezone.utc)
                    cache.set_station(station)
                    updated += 1
            except Exception as exc:
                logger.warning("TomTom unavailable for %s: %s", station.station_id, exc)
        if updated:
            logger.info("Live availability refreshed from TomTom")
            return "TomTom"

    cached_live_sources = {
        station.live_source
        for station in cache.get_all_stations()
        if station.live_data and station.live_source in {"OCPI", "TomTom"}
    }
    if cached_live_sources:
        source = sorted(cached_live_sources)[0]
        logger.warning(
            "Live providers unavailable; retaining cached %s state",
            source,
        )
        cache.live_source = source
        return source

    logger.info("No live provider configured; using static station state")
    cache.live_source = "static"
    return "static"
