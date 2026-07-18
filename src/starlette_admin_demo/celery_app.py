"""Celery app for the demo's background work: keeping the dashboard cache
warm (see cache.py, stats.py) and draining the search-restamp outbox (see
search.py's `SearchRestampJob`).

`refresh_dashboard_stats` runs `cache.py`'s `refresh_all` on a schedule set by Celery
Beat (`REFRESH_INTERVAL`); `process_search_restamp_jobs` runs `search.py`'s
`process_restamp_jobs`, purely event-driven with no Beat schedule. Both wrapped
functions are `async def` (they share starlette-admin's async callback interface), but
a Celery task must be sync, so each is driven with `asyncio.run`.
"""

import asyncio

from celery import Celery

# Imported for its `@precomputed_stat` side effect: registers every stats.py
# function into cache.py's `_REGISTRY` so this worker/beat process has something to run.
from . import stats  # noqa: F401
from .cache import REDIS_URL, REFRESH_INTERVAL, close_redis, refresh_all
from .search import process_restamp_jobs

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


@celery_app.task(name="starlette_admin_demo.celery_app.process_search_restamp_jobs")
def process_search_restamp_jobs() -> None:
    loop = get_or_create_event_loop()
    loop.run_until_complete(process_restamp_jobs())
