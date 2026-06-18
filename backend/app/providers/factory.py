"""Provider selection.

Reads ``settings.data_provider`` and returns the appropriate concrete provider.
When ``settings.data_provider_cache`` is True, the raw provider is wrapped in
a ``CachingProviderWrapper`` that stores results in Redis with per-method TTLs.

Lazy imports keep the import graph clean (the DataGolf provider doesn't pull in
httpx into the mock-only test path; the caching wrapper doesn't pull in redis
when cache is disabled).
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from app.providers.base import DataProvider


def _build_raw_provider() -> DataProvider:
    """Instantiate the raw (uncached) provider from settings."""
    settings = get_settings()
    name = settings.data_provider

    if name == "mock":
        from app.providers.mock.mock_provider import MockDataProvider

        return MockDataProvider(seed=settings.mock_seed)

    if name == "datagolf":  # pragma: no cover — lands Phase 5
        from app.providers.datagolf.datagolf_provider import DataGolfProvider

        # Share the Redis client (when caching is on) so the provider can cache
        # immutable per-event archives durably — see DataGolfProvider._event_rows.
        redis = None
        if settings.data_provider_cache:
            from app.cache.redis import redis_client

            redis = redis_client
        return DataGolfProvider(redis=redis)

    raise ValueError(f"Unknown DATA_PROVIDER: {name!r}")


@lru_cache(maxsize=1)
def get_data_provider() -> DataProvider:
    """Return the configured provider, cached for the process lifetime.

    When ``DATA_PROVIDER_CACHE=true`` (the default) the raw provider is wrapped
    with a Redis-backed ``CachingProviderWrapper``.  Set it to ``false`` in
    tests or local dev to skip Redis entirely.

    Clear the cache with ``get_data_provider.cache_clear()`` in tests that
    need to swap providers mid-run.
    """
    settings = get_settings()
    raw = _build_raw_provider()

    if not settings.data_provider_cache:
        return raw

    # Wrap with Redis cache.  Import is lazy so the redis client is only
    # created when caching is actually enabled.
    from app.cache.redis import redis_client
    from app.providers.caching import CachingProviderWrapper

    return CachingProviderWrapper(raw, redis=redis_client)
