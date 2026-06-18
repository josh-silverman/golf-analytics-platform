"""Prediction endpoints — leaderboard for one tournament."""

from __future__ import annotations

from datetime import date  # noqa: TC003
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.deps import get_prediction_service
from app.api.v1.schemas import PlayerOutcomePayload, TournamentPredictionsPayload
from app.config import get_settings
from app.services.catalog import reference_today
from app.services.predictions import PredictionService  # noqa: TC001

router = APIRouter(tags=["predictions"], prefix="/predictions")

# The assembled leaderboard is expensive to build (a field-wide feature
# extraction over ~150 players), but it's stable for a given (tournament, as_of)
# within a day. Caching the finished board in Redis turns repeat and concurrent
# loads into a single fast lookup instead of each re-running the extraction —
# which is what previously let overlapping requests pile onto the throttled
# DataGolf fetch and stall the page. An upcoming/in-progress event's board
# barely moves between refreshes, so a multi-hour TTL keeps loads instant while
# still refreshing within a day (and the key includes as_of, so a new day always
# recomputes once).
_BOARD_TTL_S = 21_600  # 6 h


async def _cached_board(cache_key: str) -> TournamentPredictionsPayload | None:
    """Best-effort read of a cached board; ``None`` on miss/any error."""
    from app.cache.redis import redis_client

    try:
        raw = await redis_client.get(cache_key)
        return TournamentPredictionsPayload.model_validate_json(raw) if raw else None
    except Exception:  # noqa: BLE001 — cache is best-effort, never block serving
        return None


async def _store_board(cache_key: str, payload: TournamentPredictionsPayload) -> None:
    """Best-effort write of a computed board."""
    from app.cache.redis import redis_client

    try:
        await redis_client.setex(cache_key, _BOARD_TTL_S, payload.model_dump_json())
    except Exception:  # noqa: BLE001 — best-effort
        return


@router.get("/{tournament_id}")
async def predict_tournament(
    tournament_id: int,
    service: Annotated[PredictionService, Depends(get_prediction_service)],
    as_of: date | None = Query(default=None),  # noqa: B008
) -> TournamentPredictionsPayload:
    """Leaderboard of win/top-N/make-cut probabilities for a tournament.

    When ``as_of`` is omitted, the catalog's reference date is used so the
    response stays consistent with the rest of the dashboard.
    """
    target = as_of or reference_today()
    cache_enabled = get_settings().data_provider_cache
    cache_key = f"pga:board:predictions:{tournament_id}:{target.isoformat()}"

    if cache_enabled:
        cached = await _cached_board(cache_key)
        if cached is not None:
            return cached

    predictions = await service.predict_tournament(tournament_id, as_of=target)
    if predictions is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tournament {tournament_id} not found",
        )
    payload = TournamentPredictionsPayload(
        tournament_id=predictions.tournament_id,
        tournament_name=predictions.tournament_name,
        as_of=predictions.as_of,
        model_name=predictions.model_name,
        model_version_id=predictions.model_version_id,
        feature_set_hash=predictions.feature_set_hash,
        outcomes=[
            PlayerOutcomePayload(
                player_id=o.player_id,
                player_name=o.player_name,
                win_prob=o.win_prob,
                top_5_prob=o.top_5_prob,
                top_10_prob=o.top_10_prob,
                top_20_prob=o.top_20_prob,
                make_cut_prob=o.make_cut_prob,
                final_position=o.final_position,
                made_cut=o.made_cut,
            )
            for o in predictions.outcomes
        ],
    )
    if cache_enabled:
        await _store_board(cache_key, payload)
    return payload
