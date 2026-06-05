"""Simulation endpoint — MC-derived outcome distributions for one tournament.

Decision 4 (doc 01 §3) calls for Approach C: skill rating → simulation →
probabilities.  This endpoint runs the Monte Carlo engine synchronously
(~330ms for 10k iterations over a 156-player field) and returns coherent
outcome distributions where win ≤ top-5 ≤ top-10 ≤ make-cut by construction.

The predictions endpoint (``/predictions/{id}``) continues to serve the
GBDT classifier's per-outcome probabilities as a second signal.  Showing both
on the frontend is a natural portfolio demonstration of the two approaches.
"""

from __future__ import annotations

from datetime import date  # noqa: TC003 — FastAPI resolves at runtime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.deps import get_simulation_service
from app.api.v1.schemas import SimulationOutcomePayload, TournamentSimulationPayload
from app.services.catalog import reference_today
from app.simulation.service import SimulationService  # noqa: TC001 — FastAPI DI

router = APIRouter(tags=["simulations"], prefix="/simulations")


@router.get("/{tournament_id}")
async def simulate_tournament(
    tournament_id: int,
    service: Annotated[SimulationService, Depends(get_simulation_service)],
    as_of: date | None = Query(default=None),  # noqa: B008
) -> TournamentSimulationPayload:
    """Run a 10k-iteration Monte Carlo simulation for ``tournament_id``.

    Outcome probabilities are derived from the simulation, not the ML
    classifier, and are guaranteed to be coherent (win ≤ top-5 ≤ top-10 ≤
    top-20 ≤ make-cut).
    """
    target = as_of or reference_today()
    result = await service.simulate_tournament(tournament_id, as_of=target)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tournament {tournament_id} not found",
        )
    return TournamentSimulationPayload(
        tournament_id=result.tournament_id,
        tournament_name=result.tournament_name,
        as_of=result.as_of,  # type: ignore[arg-type]
        n_iterations=result.n_iterations,
        score_std=result.score_std,
        outcomes=[
            SimulationOutcomePayload(
                player_id=o.player_id,
                player_name=o.player_name,
                win_prob=o.win_prob,
                top_5_prob=o.top_5_prob,
                top_10_prob=o.top_10_prob,
                top_20_prob=o.top_20_prob,
                make_cut_prob=o.make_cut_prob,
                expected_score=o.expected_score,
            )
            for o in result.outcomes
        ],
    )
