"""FastAPI dependency providers for the v1 API.

Lifecycle: ``CatalogService`` is per-request; the underlying ``DataProvider``
is process-cached by ``get_data_provider`` so the mock dataset isn't
re-generated on every request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import Depends

from app.providers.factory import get_data_provider
from app.services.catalog import CatalogService

if TYPE_CHECKING:
    from app.providers.base import DataProvider


def _provider_dep() -> DataProvider:
    return get_data_provider()


def get_catalog_service(
    provider: DataProvider = Depends(_provider_dep),  # noqa: B008 — FastAPI DI
) -> CatalogService:
    return CatalogService(provider)
