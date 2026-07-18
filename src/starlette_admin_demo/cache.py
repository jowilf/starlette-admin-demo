"""Background precomputation for the dashboard's query results (see stats.py, dashboard.py), cached in Redis and computed by Celery (see celery_app.py).

`precomputed_stat(key)` wraps a `stats.py` function to register it for `refresh_all` and returns a
read-only widget callback that only reads Redis, so a dashboard page load never blocks on a query.
"""

from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
import json
import logging
import os
from typing import Any

import redis.asyncio as redis_asyncio
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette_admin.events import (
    AdminEvent,
    AdminEventSubscriber,
    AfterCreateContext,
    AfterDeleteContext,
    AfterEditContext,
    AfterImportContext,
    on,
)

from .config import engine

_log = logging.getLogger(__name__)

DASHBOARD_CACHE_GROUP = "dashboard"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
# How often Celery Beat schedules `refresh_dashboard_stats`, in seconds.
REFRESH_INTERVAL = int(os.getenv("DASHBOARD_REFRESH_INTERVAL", "60"))
# Backstop only: if Beat/worker stop, a stale entry falls back to serving each callback's `default` after this many seconds.
DASHBOARD_CACHE_TTL = int(os.getenv("DASHBOARD_CACHE_TTL", "300"))

_redis = redis_asyncio.Redis.from_url(REDIS_URL)

# Populated by `precomputed_stat`; consumed by `refresh_all`.
_REGISTRY: dict[str, Callable[[Session], Awaitable[Any]]] = {}


def _cache_key(key: str) -> str:
    return f"{DASHBOARD_CACHE_GROUP}:{key}"


async def _cache_get(key: str) -> Any | None:
    raw = await _redis.get(_cache_key(key))
    return None if raw is None else json.loads(raw)


async def _cache_set(key: str, value: Any, *, ttl: int) -> None:
    await _redis.set(_cache_key(key), json.dumps(value), ex=ttl)


def precomputed_stat(
    key: str, default: Any = None
) -> Callable[
    [Callable[[Session], Awaitable[Any]]], Callable[[Request], Awaitable[Any]]
]:
    """Register a `stats.py` function under `key` for `refresh_all`, and return the read-only widget callback `dashboard.py` calls instead.

    A cache miss just serves `default`; the callback never falls back to computing inline.
    """

    def decorator(
        fn: Callable[[Session], Awaitable[Any]],
    ) -> Callable[[Request], Awaitable[Any]]:
        _REGISTRY[key] = fn

        async def wrapper(_request: Request) -> Any:
            cached = await _cache_get(key)
            return default if cached is None else cached

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    return decorator


async def refresh_all() -> None:
    with Session(engine) as session:
        for key, fn in _REGISTRY.items():
            try:
                value = await fn(session)
            except Exception:
                _log.exception("Dashboard cache refresh failed for %r", key)
                continue
            await _cache_set(key, value, ttl=DASHBOARD_CACHE_TTL)


async def close_redis() -> None:
    """Disconnect the shared client's pooled connections; must be called at the end of every `asyncio.run(refresh_all())` (see celery_app.py)."""
    await _redis.aclose()


def trigger_dashboard_refresh() -> None:
    """Enqueue `refresh_dashboard_stats` (see celery_app.py) for a worker to pick up now, instead of waiting out Beat's schedule.

    Imports `celery_app` lazily so this module doesn't pay to build the `Celery` app unless needed.
    """
    from .celery_app import refresh_dashboard_stats

    refresh_dashboard_stats.delay()


@asynccontextmanager
async def dashboard_cache_lifespan():
    """Closes the Redis connection on app shutdown; the cache itself is kept warm by Celery Beat and a worker, not this process."""
    try:
        yield
    finally:
        await close_redis()


class DashboardCacheSubscriber(AdminEventSubscriber):
    """Subscribed admin-wide: `admin.events.subscribe(DashboardCacheSubscriber())`."""

    @on(AdminEvent.AFTER_CREATE_COMMITTED)
    async def refresh_on_create(self, ctx: AfterCreateContext) -> None:
        trigger_dashboard_refresh()

    @on(AdminEvent.AFTER_EDIT_COMMITTED)
    async def refresh_on_edit(self, ctx: AfterEditContext) -> None:
        trigger_dashboard_refresh()

    @on(AdminEvent.AFTER_DELETE_COMMITTED)
    async def refresh_on_delete(self, ctx: AfterDeleteContext) -> None:
        trigger_dashboard_refresh()

    @on(AdminEvent.AFTER_IMPORT)
    async def refresh_on_import(self, ctx: AfterImportContext) -> None:
        trigger_dashboard_refresh()
