"""Prediction endpoints — leaderboard for one tournament."""

from __future__ import annotations

from datetime import date  # noqa: TC003
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.deps import get_prediction_service
from app.api.v1.schemas import PlayerOutcomePayload, TournamentPredictionsPayload
from app.services.catalog import reference_today
from app.services.predictions import PredictionService  # noqa: TC001

router = APIRouter(tags=["predictions"], prefix="/predictions")


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
    predictions = await service.predict_tournament(tournament_id, as_of=target)
    if predictions is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tournament {tournament_id} not found",
        )
    return TournamentPredictionsPayload(
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
            )
            for o in predictions.outcomes
        ],
    )
