"""Betting edge endpoint — board vs. market divergence for one tournament.

Serves the Market Comparison page (narrowed from a betting tool: no EV, no
Kelly stake sizing, no +EV recommendation — see ``services/betting.py``).

The approach:

1. Run the calibrated classifier to get model probability estimates. Its
   field-normalized outputs sum to each market's true total, so longshots
   aren't over-priced.
2. Use real sportsbook odds when the provider has a live feed (DataGolf),
   de-vigged to a fair implied probability; fall back to a synthetic line
   per player otherwise (still stamped ``odds_source="model"``, so the
   frontend's real-vs-synthetic coverage count stays accurate even though it
   discards the synthetic numbers themselves).
3. Compute edge (model_prob − implied_prob).
4. Return lines sorted by edge descending.

``outcome_key`` selects the market: "win_prob", "top_5_prob", "top_10_prob",
"top_20_prob", or "make_cut_prob".  The frontend defaults to "win_prob" but
a user can switch markets via the query parameter. (Note: the model has real
out-of-sample skill on make-cut / top-20, but ~none on outright winner — the
book is razor-sharp there — so win-market divergences are mostly noise.)
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


async def _fetch_real_odds(provider: DataProvider, outcome_key: str) -> dict[int, int] | None:
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
    """Return board-vs-market divergence lines for every player in the field.

    Lines are sorted by edge (descending). ``odds_source`` is ``"datagolf"``
    when real sportsbook odds backed the board.
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
        odds_source=board.odds_source,
        lines=[
            BettingLinePayload(
                player_id=line.player_id,
                player_name=line.player_name,
                model_prob=line.model_prob,
                implied_prob=line.implied_prob,
                american_odds=line.american_odds,
                edge=line.edge,
                odds_source=line.odds_source,
            )
            for line in board.lines
        ],
    )
