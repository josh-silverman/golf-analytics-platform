"""Grade the forward, out-of-sample prediction-board archive.

Consumes the immutable snapshots captured by ``board_archive`` and grades only
those whose producing model was trained *strictly before* the event — a
genuinely out-of-sample record, unlike the active-model report card which can be
in-sample. Each completed, OOS-qualifying board is scored against real results;
markets are aggregated across events with a block-bootstrap CI (the same event-
resampling unit the backtest uses), so a market is only reported as "skilled"
once its lower CI clears zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.domain.enums import EntryStatus, TournamentStatus
from app.ml.backtest import _bootstrap_skill_ci, _brier

if TYPE_CHECKING:
    from app.services.board_archive import BoardArchive
    from app.services.catalog import CatalogService

_MARKETS = ("win_prob", "top_5_prob", "top_10_prob", "top_20_prob", "make_cut_prob")


@dataclass(frozen=True)
class MarketSkill:
    market: str
    n: int
    base_rate: float
    brier: float
    brier_skill: float
    ci_lower: float
    ci_upper: float


@dataclass(frozen=True)
class ForwardTrackRecord:
    """Out-of-sample accuracy accumulated from captured pre-event boards."""

    events: int
    players_graded: int
    markets: tuple[MarketSkill, ...]
    # Events still needed before the strong markets reach a stable CI (heuristic).
    events_to_meaningful: int


# Heuristic: block-bootstrap CIs over events stabilise for the strong markets
# (make-cut, top-20) at roughly the backtest's own working scale. Below this the
# CI is too wide to certify skill; win/top-5 need far more and may never certify
# at weekly cadence (data-starved).
_MEANINGFUL_EVENTS = 20


def _labels(final_position: int | None, status: EntryStatus) -> dict[str, int] | None:
    if status == EntryStatus.MADE_CUT:
        made = True
    elif status == EntryStatus.MISSED_CUT:
        made = False
    else:
        return None  # WD / active — not gradeable
    pos = final_position
    return {
        "win_prob": int(pos == 1),
        "top_5_prob": int(pos is not None and pos <= 5),
        "top_10_prob": int(pos is not None and pos <= 10),
        "top_20_prob": int(pos is not None and pos <= 20),
        "make_cut_prob": int(made),
    }


async def compute_forward_track_record(
    *,
    archive: BoardArchive,
    catalog: CatalogService,
) -> ForwardTrackRecord | None:
    """Grade every completed, out-of-sample captured board. ``None`` if none yet."""
    snapshots = archive.list_all()
    if not snapshots:
        return None

    # Per-market, grouped by event (the block-bootstrap unit).
    y_by_event: dict[str, list[list[float]]] = {m: [] for m in _MARKETS}
    p_by_event: dict[str, list[list[float]]] = {m: [] for m in _MARKETS}
    events = 0
    players = 0

    for snap in snapshots:
        tournament = await catalog.get_tournament(snap.tournament_id)
        if tournament is None or tournament.status != TournamentStatus.COMPLETED:
            continue
        if not snap.is_out_of_sample(tournament.start_date):
            continue  # model saw this event in training → not OOS, skip

        field = await catalog.get_tournament_field(snap.tournament_id)
        label_by_player = {
            e.player_id: _labels(e.final_position, e.status) for e in field
        }
        probs_by_player = {o.player_id: o for o in snap.outcomes}

        ev_y: dict[str, list[float]] = {m: [] for m in _MARKETS}
        ev_p: dict[str, list[float]] = {m: [] for m in _MARKETS}
        graded_here = 0
        for pid, lab in label_by_player.items():
            if lab is None or pid not in probs_by_player:
                continue
            o = probs_by_player[pid]
            graded_here += 1
            for m in _MARKETS:
                ev_y[m].append(float(lab[m]))
                ev_p[m].append(float(getattr(o, m)))
        if graded_here == 0:
            continue
        events += 1
        players += graded_here
        for m in _MARKETS:
            y_by_event[m].append(ev_y[m])
            p_by_event[m].append(ev_p[m])

    if events == 0:
        return None

    markets: list[MarketSkill] = []
    for m in _MARKETS:
        y_flat = [v for ev in y_by_event[m] for v in ev]
        p_flat = [v for ev in p_by_event[m] for v in ev]
        if not y_flat:
            continue
        base = sum(y_flat) / len(y_flat)
        brier = _brier(_np(y_flat), _np(p_flat))
        base_brier = _brier(_np(y_flat), _np([base] * len(y_flat)))
        skill = 1.0 - brier / base_brier if base_brier > 0 else 0.0
        lo, hi = _bootstrap_skill_ci(
            [_np(ev) for ev in y_by_event[m]],
            [_np(ev) for ev in p_by_event[m]],
            n_reps=2000,
            ci=0.90,
        )
        markets.append(
            MarketSkill(m, len(y_flat), base, brier, skill, lo, hi)
        )

    return ForwardTrackRecord(
        events=events,
        players_graded=players,
        markets=tuple(markets),
        events_to_meaningful=max(0, _MEANINGFUL_EVENTS - events),
    )


def _np(values: list[float]):  # noqa: ANN202 — thin import-local helper
    import numpy as np

    return np.array(values, dtype=np.float64)
