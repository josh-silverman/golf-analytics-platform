"""Metadata endpoints — data freshness, source identification."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.v1.deps import get_catalog_service
from app.domain.models import DataFreshness  # noqa: TC001
from app.services.catalog import CatalogService  # noqa: TC001

router = APIRouter(tags=["meta"], prefix="/meta")


@router.get("/data-freshness")
async def data_freshness(
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
) -> DataFreshness:
    return await catalog.data_freshness()
