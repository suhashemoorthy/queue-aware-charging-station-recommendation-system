import asyncio
from types import SimpleNamespace

from app import collector as collector_module
from app.cache import StationCache
from app.collector import StationCollector
from app.config import Settings


def make_collector():
    return StationCollector(Settings(), SimpleNamespace(all=lambda: []), StationCache())


def test_start_is_idempotent(monkeypatch):
    async def scenario():
        collector = make_collector()

        async def wait_forever():
            await asyncio.Event().wait()

        monkeypatch.setattr(collector, "_run", wait_forever)
        await collector.start()
        task = collector._task
        await collector.start()

        assert collector._task is task
        await collector.stop()

    asyncio.run(scenario())


def test_live_refreshes_do_not_overlap(monkeypatch):
    async def scenario():
        collector = make_collector()
        entered = asyncio.Event()
        release = asyncio.Event()
        active = 0
        maximum_active = 0

        async def refresh(*_args):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            entered.set()
            await release.wait()
            active -= 1
            return "static"

        monkeypatch.setattr(collector_module, "refresh_live_data", refresh)
        first = asyncio.create_task(collector.refresh_live())
        await entered.wait()
        second = asyncio.create_task(collector.refresh_live())
        await asyncio.sleep(0)
        assert maximum_active == 1

        release.set()
        assert await asyncio.gather(first, second) == ["static", "static"]
        assert maximum_active == 1

    asyncio.run(scenario())