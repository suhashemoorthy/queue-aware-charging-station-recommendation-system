import asyncio
import logging

from .cache import StationCache
from .config import Settings
from .live_data import refresh_live_data
from .ocpi import OCPIClient
from .osm import OSMError, OverpassClient
from .repository import StationRepository
from .tomtom import TomTomClient

logger = logging.getLogger(__name__)


class StationCollector:
    def __init__(self, settings: Settings, repository: StationRepository, cache: StationCache) -> None:
        self.settings = settings
        self.repository = repository
        self.cache = cache
        self.overpass = OverpassClient(settings.overpass_url)
        self.ocpi = OCPIClient(settings.ocpi_base_url, settings.ocpi_token, settings.ocpi_location_endpoint, settings.ocpi_status_endpoint)
        self.tomtom = TomTomClient(settings.tomtom_api_key)
        self._task: asyncio.Task[None] | None = None
        self._refresh_lock = asyncio.Lock()

    async def refresh_stations(self) -> None:
        async with self._refresh_lock:
            await self._refresh_stations()

    async def _refresh_stations(self) -> None:
        if not self.settings.enable_osm_refresh:
            return
        try:
            stations = await self.overpass.get_stations()
            if stations:
                self.cache.set_stations(stations)
                return
        except OSMError as exc:
            logger.warning("OSM refresh failed; retaining repository/cache: %s", exc)
        if not self.cache.get_all_stations():
            self.cache.set_stations(self.repository.all())

    async def refresh_live(self) -> str:
        async with self._refresh_lock:
            return await self._refresh_live()

    async def _refresh_live(self) -> str:
        stations = self.cache.get_all_stations()
        return await refresh_live_data(stations, self.cache, self.ocpi, self.tomtom)

    async def run_once(self) -> None:
        async with self._refresh_lock:
            await self._refresh_stations()
            await self._refresh_live()

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        if not self.cache.get_all_stations():
            self.cache.set_stations(self.repository.all())
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        await self.run_once()
        elapsed_since_station = 0
        elapsed_since_live = 0
        interval = max(
            1,
            min(
                self.settings.station_refresh_seconds,
                self.settings.live_refresh_seconds,
            ),
        )
        while True:
            await asyncio.sleep(interval)
            elapsed_since_station += interval
            elapsed_since_live += interval
            if elapsed_since_station >= self.settings.station_refresh_seconds:
                await self.refresh_stations()
                elapsed_since_station = 0
            if elapsed_since_live >= self.settings.live_refresh_seconds:
                await self.refresh_live()
                elapsed_since_live = 0

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
