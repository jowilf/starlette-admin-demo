"""Celery app for the demo's background work: keeping the dashboard cache
warm (see cache.py, stats.py).

`refresh_dashboard_stats` runs `cache.py`'s `refresh_all` on a schedule set by Celery
Beat (`REFRESH_INTERVAL`). It's wrapped as `async def` (it shares starlette-admin's
async callback interface), but a Celery task must be sync, so it's driven with
`asyncio.run`.
"""

import asyncio

from celery import Celery

# Imported for its `@precomputed_stat` side effect: registers every stats.py
# function into cache.py's `_REGISTRY` so this worker/beat process has something to run.
from . import stats  # noqa: F401
from .cache import REDIS_URL, REFRESH_INTERVAL, close_redis, refresh_all

celery_app = Celery("starlette_admin_demo", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "refresh-dashboard-stats": {
        "task": "starlette_admin_demo.celery_app.refresh_dashboard_stats",
        "schedule": REFRESH_INTERVAL,
    },
}


def get_or_create_event_loop():
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


@celery_app.task(name="starlette_admin_demo.celery_app.refresh_dashboard_stats")
def refresh_dashboard_stats() -> None:
    loop = get_or_create_event_loop()
    loop.run_until_complete(_refresh_and_close())


async def _refresh_and_close() -> None:
    try:
        await refresh_all()
    finally:
        await close_redis()
