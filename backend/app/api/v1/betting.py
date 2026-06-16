"""Betting edge endpoint — Kelly-sized +EV opportunities for one tournament.

The approach (doc 01 §4 Phase 4):

1. Run the calibrated classifier to get model probability estimates. The
   classifier is used (not the Monte-Carlo sim) because a real-data backtest
   showed it is better-calibrated on every market — and EV sizing is only as
   trustworthy as the probabilities' calibration. Its field-normalized outputs
   also sum to each market's true total, so longshots aren't over-priced.
2. Use real sportsbook odds when the provider has a live feed (DataGolf),
   de-vigged to a fair implied probability; fall back to a synthetic line
   per player otherwise.
3. Compute edge (model_prob − implied_prob) and half-Kelly stake size.
4. Return lines sorted by EV descending so the frontend can show the
   best bets first.

``outcome_key`` selects the market: "win_prob", "top_5_prob", "top_10_prob",
"top_20_prob", or "make_cut_prob".  The frontend defaults to "win_prob" but
a user can switch markets via the query parameter. (Note: the model has real
out-of-sample skill on make-cut / top-20, but ~none on outright winner — the
book is razor-sharp there — so win-market "edges" are mostly noise.)
"""

from __future__ import annotations

from datetime import date  # noqa: TC003 — FastAPI resolves at runtime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.deps import get_prediction_service
from app.api.v1.schemas import BettingBoardPayload, BettingLinePayload
from app.providers.base import DataProvider  # noqa: TC001 — FastAPI DI
from app.providers.factory import get_data_provider
from app.services.betting import build_betting_board
from app.services.catalog import reference_today
from app.services.predictions import PredictionService  # noqa: TC001 — FastAPI DI

router = APIRouter(tags=["betting"], prefix="/betting")

OutcomeKey = Literal["win_prob", "top_5_prob", "top_10_prob", "top_20_prob", "make_cut_prob"]


async def _fetch_real_odds(
    provider: DataProvider, outcome_key: str
) -> dict[int, int] | None:
    """Best-effort real outright odds; ``None`` if the provider has no feed."""
    try:
        board = await provider.get_outright_odds(outcome_key)
    except Exception:  # noqa: BLE001 — odds are optional; never fail the page
        return None
    return board.odds if board and board.odds else None


@router.get("/edge/{tournament_id}")
async def betting_edge(
    tournament_id: int,
    service: Annotated[PredictionService, Depends(get_prediction_service)],
    provider: Annotated[DataProvider, Depends(get_data_provider)],
    outcome_key: OutcomeKey = Query(default="win_prob"),  # noqa: B008
    as_of: date | None = Query(default=None),  # noqa: B008
) -> BettingBoardPayload:
    """Return +EV betting lines for every player in the tournament field.

    Lines are sorted by expected value per dollar wagered (descending).
    ``n_positive_ev`` is a convenience count of lines where edge ≥ 0.5%.
    ``odds_source`` is ``"datagolf"`` when real sportsbook odds backed the board.
    """
    target = as_of or reference_today()
    result = await service.predict_tournament(tournament_id, as_of=target)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tournament {tournament_id} not found",
        )

    real_odds = await _fetch_real_odds(provider, outcome_key)

    board = build_betting_board(
        result.outcomes,
        tournament_id=result.tournament_id,
        tournament_name=result.tournament_name,
        outcome_key=outcome_key,
        real_odds=real_odds,
    )

    return BettingBoardPayload(
        tournament_id=board.tournament_id,
        tournament_name=board.tournament_name,
        outcome_key=board.outcome_key,
        n_positive_ev=len(board.positive_ev_lines),
        odds_source=board.odds_source,
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
                odds_source=line.odds_source,
            )
            for line in board.lines
        ],
    )
