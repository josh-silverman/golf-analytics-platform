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
from app.services.settlement_archive import settlement_from_field

if TYPE_CHECKING:
    from collections.abc import Iterable

    import numpy as np
    from numpy.typing import NDArray

    from app.services.board_archive import BoardArchive, BoardSnapshot
    from app.services.catalog import CatalogService
    from app.services.settlement_archive import SettlementArchive

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
    # Graded events whose board was served with DataGolf-direct probabilities
    # for most of the field, i.e. Path A actually running. Reported because the
    # record spans the 2026-07-29 fix for the caching-wrapper bug that silently
    # cold-started every player: boards from either side of it are stamped with
    # the same "path_a@…" version id, so without this the aggregate pools two
    # different serving systems under one number. ``None`` for boards captured
    # before coverage was recorded at all, counted separately as "unknown".
    events_path_a: int = 0
    events_cold_start_only: int = 0
    events_regime_unknown: int = 0
    # Provenance split of the graded events: a live pre-event capture is
    # primary evidence; a backfill is a post-hoc reconstruction by whatever
    # code was current when it ran. Pooled in ``markets``, but also aggregated
    # separately below so a surface can show the two classes of evidence side
    # by side instead of passing a pooled figure off as a live record.
    events_captured: int = 0
    events_backfilled: int = 0
    players_captured: int = 0
    players_backfilled: int = 0
    # Same per-market aggregation as ``markets``, restricted to one provenance.
    # CIs are None until a pool has enough events to bootstrap.
    markets_captured: tuple[MarketSkill, ...] = ()
    markets_backfilled: tuple[MarketSkill, ...] = ()


# Heuristic: block-bootstrap CIs over events stabilise for the strong markets
# (make-cut, top-20) at roughly the backtest's own working scale. Below this the
# CI is too wide to certify skill; win/top-5 need far more and may never certify
# at weekly cadence (data-starved).
_MEANINGFUL_EVENTS = 20

# Share of a field that must have been served DataGolf-direct before the board
# counts as "Path A actually ran". DataGolf covers ~95% of a typical field, so a
# healthy board sits far above this; the failure mode being separated out is the
# degenerate one (nothing came back, whole field cold-started), which sits at 0.
_PATH_A_COVERAGE_FLOOR = 0.5


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


def event_has_a_cut(statuses: Iterable[EntryStatus]) -> bool:
    """Did this event actually cut anyone?

    The FedExCup playoff events and several limited-field events play all four
    rounds with no 36-hole cut. Every player is graded as having made it, so
    the make-cut market on those events scores a question that was never asked.

    The contamination does not have a fixed sign, which is why it has to be
    excluded rather than corrected: served DataGolf-direct it reports 1.0 for
    everyone and scores perfectly, inflating the aggregate (measured at about
    +0.065 of skill for three no-cut events among ten); served by the
    cold-start model, which has no idea the cut was waived, it predicts a
    normal spread and scores badly, deflating it. Either way the number stops
    describing real make-cut skill, and this is the market the product claims
    as its strongest. Excluded from the make-cut aggregate only; every other
    market on those events grades normally.

    Public for the same reason as ``canonical_by_tournament``: the read-only
    board view must not disagree with the grader about whether an event had a
    cut, or it would show a make-cut figure the record deliberately excludes.
    """
    return any(s == EntryStatus.MISSED_CUT for s in statuses)


def canonical_by_tournament(snapshots: list[BoardSnapshot]) -> dict[int, BoardSnapshot]:
    """The one snapshot per tournament that the forward record grades.

    The archive legitimately holds several snapshots of one event — retraining
    changes the ``model_version_id``, so an event can be captured live under one
    version and reconstructed by the backfill under another — but grading them
    all would count the tournament twice (twice the events, twice the bootstrap
    blocks). The canonical snapshot is the earliest live capture: ``captured``
    beats ``backfilled`` regardless of timestamp (primary evidence over
    reconstruction), earliest ``captured_at`` breaking ties within a source.

    Shared with the read-only archive inspector so the debugging view cannot
    disagree with the grader about which snapshot actually counts.
    """
    canonical: dict[int, BoardSnapshot] = {}
    for snap in snapshots:
        rank = (snap.source != "captured", snap.captured_at)
        held = canonical.get(snap.tournament_id)
        if held is None or rank < (held.source != "captured", held.captured_at):
            canonical[snap.tournament_id] = snap
    return canonical


async def compute_forward_track_record(
    *,
    archive: BoardArchive,
    catalog: CatalogService,
    settlements: SettlementArchive | None = None,
) -> ForwardTrackRecord | None:
    """Grade every completed, out-of-sample captured board. ``None`` if none yet.

    With a ``settlements`` archive, results are read from the pinned
    settlement record for each event; the provider is consulted only to
    create a missing pin (first grade of a newly completed event), never to
    re-read one that exists. Without one (older callers, unit tests), results
    are read from the provider directly — the pre-settlement behaviour.
    """
    snapshots = await archive.list_all()
    if not snapshots:
        return None

    snapshots = list(canonical_by_tournament(snapshots).values())

    # Per-market, grouped by event (the block-bootstrap unit) — one pool for
    # the combined record and one per provenance, so captured and backfilled
    # can be reported as separate aggregates rather than only as counts.
    pools: dict[str, tuple[dict[str, list[list[float]]], dict[str, list[list[float]]]]] = {
        key: ({m: [] for m in _MARKETS}, {m: [] for m in _MARKETS})
        for key in ("all", "captured", "backfilled")
    }
    events = 0
    players = 0
    path_a_events = 0
    cold_start_events = 0
    unknown_regime_events = 0
    captured_events = 0
    backfilled_events = 0
    captured_players = 0
    backfilled_players = 0

    for snap in snapshots:
        tournament = await catalog.get_tournament(snap.tournament_id)
        if tournament is None or tournament.status != TournamentStatus.COMPLETED:
            continue
        if not snap.is_out_of_sample(tournament.start_date):
            continue  # model saw this event in training → not OOS, skip

        # Results: from the pinned settlement when an archive is provided, so
        # a provider-side revision can never rewrite an already-graded event.
        # Both sources reduce to the same (player, position, status) rows and
        # flow through the same labelling below, so pinning cannot change the
        # grading semantics — only where the inputs come from.
        results: list[tuple[int, int | None, EntryStatus]] = []
        if settlements is not None:
            stored = await settlements.get(snap.tournament_id)
            if stored is None:
                field = await catalog.get_tournament_field(snap.tournament_id)
                if not field:
                    continue  # no field → nothing to pin, nothing to grade
                candidate = settlement_from_field(tournament, field, provider=catalog.source_name)
                if await settlements.persist(candidate):
                    stored = candidate
                else:
                    # Lost a first-write race: whatever landed first is the
                    # truth; this run's provider read is discarded.
                    stored = await settlements.get(snap.tournament_id) or candidate
            for e in stored.entries:
                st = e.entry_status()
                if st is not None:  # unrecognised stored status → ungradeable
                    results.append((e.player_id, e.final_position, st))
        else:
            field = await catalog.get_tournament_field(snap.tournament_id)
            results = [(e.player_id, e.final_position, e.status) for e in field]

        label_by_player = {pid: _labels(pos, st) for pid, pos, st in results}
        probs_by_player = {o.player_id: o for o in snap.outcomes}
        # Markets this event can legitimately be graded on.
        gradeable = [
            m
            for m in _MARKETS
            if m != "make_cut_prob" or event_has_a_cut(st for _, _, st in results)
        ]

        ev_y: dict[str, list[float]] = {m: [] for m in _MARKETS}
        ev_p: dict[str, list[float]] = {m: [] for m in _MARKETS}
        graded_here = 0
        for pid, lab in label_by_player.items():
            if lab is None or pid not in probs_by_player:
                continue
            o = probs_by_player[pid]
            graded_here += 1
            for m in gradeable:
                ev_y[m].append(float(lab[m]))
                ev_p[m].append(float(getattr(o, m)))
        if graded_here == 0:
            continue
        events += 1
        players += graded_here
        if snap.source == "captured":
            captured_events += 1
            captured_players += graded_here
        else:
            backfilled_events += 1
            backfilled_players += graded_here
        share = snap.dg_direct_share
        if share is None:
            unknown_regime_events += 1
        elif share >= _PATH_A_COVERAGE_FLOOR:
            path_a_events += 1
        else:
            cold_start_events += 1
        provenance = "captured" if snap.source == "captured" else "backfilled"
        for m in gradeable:
            # An event contributes to a market's bootstrap only if it produced
            # rows for it, so a no-cut event is absent from the make-cut
            # resampling pool rather than present as a zero-variance block.
            if ev_y[m]:
                for key in ("all", provenance):
                    pools[key][0][m].append(ev_y[m])
                    pools[key][1][m].append(ev_p[m])

    if events == 0:
        return None

    return ForwardTrackRecord(
        events=events,
        players_graded=players,
        markets=_aggregate_markets(*pools["all"]),
        events_to_meaningful=max(0, _MEANINGFUL_EVENTS - events),
        events_path_a=path_a_events,
        events_cold_start_only=cold_start_events,
        events_regime_unknown=unknown_regime_events,
        events_captured=captured_events,
        events_backfilled=backfilled_events,
        players_captured=captured_players,
        players_backfilled=backfilled_players,
        markets_captured=_aggregate_markets(*pools["captured"]),
        markets_backfilled=_aggregate_markets(*pools["backfilled"]),
    )


def _aggregate_markets(
    y_by_event: dict[str, list[list[float]]],
    p_by_event: dict[str, list[list[float]]],
) -> tuple[MarketSkill, ...]:
    """Per-market Brier skill + block-bootstrap CI over one pool of events."""
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
        markets.append(MarketSkill(m, len(y_flat), base, brier, skill, lo, hi))
    return tuple(markets)


def _np(values: list[float]) -> NDArray[np.float64]:
    import numpy as np

    return np.array(values, dtype=np.float64)
