"""Betting edge endpoint — Kelly-sized +EV opportunities for one tournament.

The approach (doc 01 §4 Phase 4):

1. Run the MC simulation to get model probability estimates.
2. Generate mock sportsbook odds with a realistic vig margin.
3. Compute edge (model_prob − implied_prob) and half-Kelly stake size.
4. Return lines sorted by EV descending so the frontend can show the
   best bets first.

``outcome_key`` selects the market: "win_prob", "top_5_prob", "top_10_prob",
"top_20_prob", or "make_cut_prob".  The frontend defaults to "win_prob" but
a user can switch markets via the query parameter.
"""

from __future__ import annotations

from datetime import date  # noqa: TC003 — FastAPI resolves at runtime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.deps import get_simulation_service
from app.api.v1.schemas import BettingBoardPayload, BettingLinePayload
from app.services.betting import build_betting_board
from app.services.catalog import reference_today
from app.simulation.service import SimulationService  # noqa: TC001 — FastAPI DI

router = APIRouter(tags=["betting"], prefix="/betting")

OutcomeKey = Literal["win_prob", "top_5_prob", "top_10_prob", "top_20_prob", "make_cut_prob"]


@router.get("/edge/{tournament_id}")
async def betting_edge(
    tournament_id: int,
    service: Annotated[SimulationService, Depends(get_simulation_service)],
    outcome_key: OutcomeKey = Query(default="win_prob"),  # noqa: B008
    as_of: date | None = Query(default=None),  # noqa: B008
) -> BettingBoardPayload:
    """Return +EV betting lines for every player in the tournament field.

    Lines are sorted by expected value per dollar wagered (descending).
    ``n_positive_ev`` is a convenience count of lines where edge ≥ 0.5%.
    """
    target = as_of or reference_today()
    result = await service.simulate_tournament(tournament_id, as_of=target)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tournament {tournament_id} not found",
        )

    board = build_betting_board(
        result.outcomes,
        tournament_id=result.tournament_id,
        tournament_name=result.tournament_name,
        outcome_key=outcome_key,
    )

    return BettingBoardPayload(
        tournament_id=board.tournament_id,
        tournament_name=board.tournament_name,
        outcome_key=board.outcome_key,
        n_positive_ev=len(board.positive_ev_lines),
        lines=[
            BettingLinePayload(
                player_id=line.player_id,
                player_name=line.player_name,
                model_prob=line.model_prob,
                implied_prob=line.implied_prob,
                american_odds=line.american_odds,
                edge=line.edge,
                ev_per_dollar=line.ev_per_dollar,
                kelly_fraction=line.kelly_fraction,
            )
            for line in board.lines
        ],
    )
