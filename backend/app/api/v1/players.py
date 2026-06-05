"""Player endpoints — /players, /players/{id}, /players/{id}/recent-rounds."""

from __future__ import annotations

from datetime import date  # noqa: TC003
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.deps import get_catalog_service, get_feature_extractor
from app.api.v1.schemas import (
    FeatureExtractionPayload,
    ListEnvelope,
    PageMeta,
    ResponseMeta,
    SingleEnvelope,
)
from app.domain.models import Player, Round
from app.services.catalog import CatalogService, reference_today  # noqa: TC001
from app.services.features import FeatureExtractor  # noqa: TC001

router = APIRouter(tags=["players"], prefix="/players")


@router.get("")
async def list_players(
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> ListEnvelope[Player]:
    page = await catalog.list_players(cursor=cursor, limit=limit)
    freshness = await catalog.data_freshness()
    return ListEnvelope[Player](
        data=page.items,
        page=PageMeta(
            next_cursor=page.next_cursor,
            has_more=page.next_cursor is not None,
            total=page.total,
        ),
        meta=ResponseMeta(
            as_of=freshness.sources.get("players", freshness.sources["players"]),
            source=catalog.source_name,
        ),
    )


@router.get("/{player_id}")
async def get_player(
    player_id: int,
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
) -> SingleEnvelope[Player]:
    player = await catalog.get_player(player_id)
    if player is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player {player_id} not found",
        )
    freshness = await catalog.data_freshness()
    return SingleEnvelope[Player](
        data=player,
        meta=ResponseMeta(
            as_of=freshness.sources["players"],
            source=catalog.source_name,
        ),
    )


@router.get("/{player_id}/recent-rounds")
async def recent_rounds(
    player_id: int,
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    limit: int = Query(default=20, ge=1, le=200),
) -> ListEnvelope[Round]:
    # Ensure player exists so we 404 instead of returning an empty list
    if await catalog.get_player(player_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player {player_id} not found",
        )
    rounds = await catalog.recent_rounds_for_player(player_id, limit=limit)
    freshness = await catalog.data_freshness()
    return ListEnvelope[Round](
        data=rounds,
        page=PageMeta(next_cursor=None, has_more=False, total=len(rounds)),
        meta=ResponseMeta(
            as_of=freshness.sources["rounds"],
            source=catalog.source_name,
        ),
    )


@router.get("/{player_id}/features")
async def get_player_features(
    player_id: int,
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    extractor: Annotated[FeatureExtractor, Depends(get_feature_extractor)],
    as_of: date | None = Query(default=None),  # noqa: B008
) -> FeatureExtractionPayload:
    """Compute the v1 baseline feature set for a player as of a given date.

    When ``as_of`` is omitted, falls back to the reference date the mock
    generator uses so the values match the rest of the dashboard.
    """
    if await catalog.get_player(player_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Player {player_id} not found",
        )
    target = as_of or reference_today()
    extraction = await extractor.extract(player_id, target)
    return FeatureExtractionPayload(
        player_id=extraction.player_id,
        as_of=extraction.as_of,
        feature_set=extraction.feature_set_name,
        feature_set_hash=extraction.feature_set_hash,
        n_rounds=extraction.n_rounds,
        values=extraction.values,
    )
