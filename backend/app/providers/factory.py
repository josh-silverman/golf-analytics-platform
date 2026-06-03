"""Provider selection.

Reads ``settings.data_provider`` and returns the appropriate concrete provider.
Lazy imports keep the import graph clean (the DataGolf provider doesn't pull in
httpx into the mock-only test path).
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from app.config import get_settings

if TYPE_CHECKING:
    from app.providers.base import DataProvider


@lru_cache(maxsize=1)
def get_data_provider() -> DataProvider:
    """Return the configured provider, cached for the process lifetime.

    The cache is keyed on nothing because settings are loaded once at process
    start; if you need to swap providers in tests, clear it with
    ``get_data_provider.cache_clear()``.
    """
    settings = get_settings()
    name = settings.data_provider

    if name == "mock":
        # Implementation lands in a follow-up commit in this phase.
        from app.providers.mock.mock_provider import (  # type: ignore[import-not-found]
            MockDataProvider,
        )

        return MockDataProvider(seed=settings.mock_seed)  # type: ignore[no-any-return]

    if name == "datagolf":  # pragma: no cover — lands Phase 5
        from app.providers.datagolf.datagolf_provider import (  # type: ignore[import-not-found]
            DataGolfProvider,
        )

        return DataGolfProvider()  # type: ignore[no-any-return]

    raise ValueError(f"Unknown DATA_PROVIDER: {name!r}")
