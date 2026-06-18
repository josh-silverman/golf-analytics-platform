"""Model track record — aggregate predicted-vs-actual accuracy over recent
completed events.

Builds on the per-event report card: for each of the last ``n_events`` completed
tournaments it scores the active model's *pre-event* board (the prediction
service caps as-of to the eve, so this is leakage-free) against what actually
happened, then aggregates. Expensive to compute (a field extraction per event),
so callers cache the result — see the ``/analytics/track-record`` endpoint.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.domain.enums import TournamentStatus
from app.services.catalog import reference_today

if TYPE_CHECKING:
    from app.services.catalog import CatalogService
    from app.services.predictions import PredictionService


@dataclass(frozen=True)
class TrackRecord:
    """Aggregate accuracy of the served model over recent completed events."""

    events: int
    players_graded: int
    winner_in_top10_rate: float  # share of events whose winner was top-10 by win%
    mean_winner_rank: float  # avg predicted rank (by win%) of the actual winner
    avg_top20_hit_rate: float  # avg share of the model's top-20 that finished top-20
    make_cut_accuracy: float  # pooled: P(make-cut call ≥50% matched reality)


async def compute_track_record(
    *,
    catalog: CatalogService,
    service: PredictionService,
    n_events: int = 8,
) -> TrackRecord | None:
    """Grade the model over the most recent ``n_events`` completed tournaments.

    Returns ``None`` when no completed event has graded results yet.
    """
    page = await catalog.list_tournaments(status=TournamentStatus.COMPLETED, limit=200)
    recent = sorted(page.items, key=lambda t: t.start_date, reverse=True)[:n_events]
    today = reference_today()

    winner_ranks: list[int] = []
    winner_top10 = 0
    top20_rates: list[float] = []
    cut_correct = 0
    cut_total = 0
    players_graded = 0
    events_used = 0

    for t in recent:
        preds = await service.predict_tournament(t.id, as_of=today)
        if preds is None:
            continue
        o = list(preds.outcomes)
        graded = [x for x in o if x.final_position is not None or x.made_cut is not None]
        if not graded:
            continue
        events_used += 1
        players_graded += len(graded)

        winner = next((x for x in o if x.final_position == 1), None)
        if winner is not None:
            by_win = sorted(o, key=lambda x: x.win_prob, reverse=True)
            rank = next(i + 1 for i, x in enumerate(by_win) if x.player_id == winner.player_id)
            winner_ranks.append(rank)
            if rank <= 10:
                winner_top10 += 1

        top20 = sorted(o, key=lambda x: x.top_20_prob, reverse=True)[:20]
        hits = sum(1 for x in top20 if x.final_position is not None and x.final_position <= 20)
        top20_rates.append(hits / 20.0)

        for x in o:
            if x.made_cut is not None:
                cut_total += 1
                if (x.make_cut_prob >= 0.5) == x.made_cut:
                    cut_correct += 1

    if events_used == 0:
        return None

    return TrackRecord(
        events=events_used,
        players_graded=players_graded,
        winner_in_top10_rate=(winner_top10 / len(winner_ranks)) if winner_ranks else 0.0,
        mean_winner_rank=statistics.mean(winner_ranks) if winner_ranks else 0.0,
        avg_top20_hit_rate=statistics.mean(top20_rates) if top20_rates else 0.0,
        make_cut_accuracy=(cut_correct / cut_total) if cut_total else 0.0,
    )
