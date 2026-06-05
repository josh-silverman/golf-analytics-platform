"""Tournament endpoints — /tournaments, /tournaments/current, /tournaments/{id},
/tournaments/{id}/field.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.deps import get_catalog_service
from app.api.v1.schemas import ListEnvelope, PageMeta, ResponseMeta, SingleEnvelope
from app.domain.enums import TournamentStatus  # noqa: TC001
from app.domain.models import Tournament, TournamentEntry
from app.services.catalog import CatalogService  # noqa: TC001

router = APIRouter(tags=["tournaments"], prefix="/tournaments")


@router.get("")
async def list_tournaments(
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    season: int | None = Query(default=None, ge=1900, le=2100),
    tournament_status: TournamentStatus | None = Query(default=None, alias="status"),  # noqa: B008
    cursor: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> ListEnvelope[Tournament]:
    page = await catalog.list_tournaments(
        season=season,
        status=tournament_status,
        cursor=cursor,
        limit=limit,
    )
    freshness = await catalog.data_freshness()
    return ListEnvelope[Tournament](
        data=page.items,
        page=PageMeta(
            next_cursor=page.next_cursor,
            has_more=page.next_cursor is not None,
            total=page.total,
        ),
        meta=ResponseMeta(
            as_of=freshness.sources["tournaments"],
            source=catalog.source_name,
        ),
    )


@router.get("/current")
async def current_tournament(
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
) -> SingleEnvelope[Tournament]:
    tournament = await catalog.get_current_tournament()
    if tournament is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No current or upcoming tournament available",
        )
    freshness = await catalog.data_freshness()
    return SingleEnvelope[Tournament](
        data=tournament,
        meta=ResponseMeta(
            as_of=freshness.sources["tournaments"],
            source=catalog.source_name,
        ),
    )


@router.get("/{tournament_id}")
async def get_tournament(
    tournament_id: int,
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
) -> SingleEnvelope[Tournament]:
    tournament = await catalog.get_tournament(tournament_id)
    if tournament is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tournament {tournament_id} not found",
        )
    freshness = await catalog.data_freshness()
    return SingleEnvelope[Tournament](
        data=tournament,
        meta=ResponseMeta(
            as_of=freshness.sources["tournaments"],
            source=catalog.source_name,
        ),
    )


@router.get("/{tournament_id}/field")
async def get_tournament_field(
    tournament_id: int,
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
) -> ListEnvelope[TournamentEntry]:
    # 404 if the tournament itself doesn't exist
    if await catalog.get_tournament(tournament_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tournament {tournament_id} not found",
        )
    field = await catalog.get_tournament_field(tournament_id)
    freshness = await catalog.data_freshness()
    return ListEnvelope[TournamentEntry](
        data=field,
        page=PageMeta(next_cursor=None, has_more=False, total=len(field)),
        meta=ResponseMeta(
            as_of=freshness.sources["tournaments"],
            source=catalog.source_name,
        ),
    )
