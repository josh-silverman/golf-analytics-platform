"""Prediction endpoints — leaderboard for one tournament."""

from __future__ import annotations

from datetime import date  # noqa: TC003
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.v1.deps import (
    get_board_archive,
    get_catalog_service,
    get_prediction_service,
    get_settlement_archive,
)
from app.api.v1.schemas import (
    ArchivedBoardOutcomePayload,
    ArchivedBoardPayload,
    ArchivedBoardSummaryPayload,
    PlayerOutcomePayload,
    TournamentPredictionsPayload,
)
from app.config import get_settings
from app.domain.enums import EntryStatus
from app.services.board_archive import BoardArchive  # noqa: TC001
from app.services.board_capture import capture_pre_event_board
from app.services.catalog import CatalogService, reference_today  # noqa: TC001
from app.services.forward_track_record import canonical_by_tournament, event_has_a_cut
from app.services.predictions import (  # noqa: TC001
    PredictionService,
    TournamentPredictions,
)
from app.services.settlement_archive import SettlementArchive  # noqa: TC001

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


async def _capture_board(
    catalog: CatalogService,
    archive: BoardArchive,
    predictions: TournamentPredictions,
) -> None:
    """Immutably capture a pre-event board for the forward OOS track record.

    Delegates the decision to ``services/board_capture``, which both this
    lazy path and the scheduled capture endpoint share, so the start guard
    cannot apply to only one of them. Never raises — archival must not break
    serving, and the scheduled path is what surfaces problems loudly.
    """
    try:
        await capture_pre_event_board(
            catalog=catalog,
            archive=archive,
            predictions=predictions,
            today=reference_today(),
        )
    except Exception:  # noqa: BLE001 — best-effort; serving must never fail on this
        return


@router.get("/archived")
async def list_archived_boards(
    board_archive: Annotated[BoardArchive, Depends(get_board_archive)],
    settlements: Annotated[SettlementArchive, Depends(get_settlement_archive)],
) -> list[ArchivedBoardSummaryPayload]:
    """Every tournament with a pinned board, newest first — metadata only.

    Backs the Track Record page's event picker and its default-event
    selection (most recent GRADED event, not most recent pinned board).
    Registered ahead of ``/{tournament_id}`` (a literal path segment must
    precede a param route — otherwise ``/archived`` is parsed as a
    tournament id and 422s, which is what happens if this function is moved
    below ``predict_tournament``; matches the convention in
    ``tournaments.py``).

    Strictly read-only, like the sibling ``/{tournament_id}/archived``: it
    creates no snapshot and pins nothing. Reuses the grader's own
    ``canonical_by_tournament`` selection so a week can never appear here
    under a snapshot the forward record itself would not have graded.

    No per-player data — no probabilities, no player names — leaves this
    endpoint. That is what makes it safe to expose publicly (ledger.md §2.8):
    it is metadata about this project's own capture activity, not DataGolf's
    per-player numbers.
    """
    snapshots = await board_archive.list_all()
    canonical = canonical_by_tournament(snapshots)
    ordered = sorted(canonical.values(), key=lambda s: s.tournament_start_date, reverse=True)
    # One bulk read rather than a per-tournament lookup. `graded` here means
    # "a settlement is pinned", not the single-board endpoint's looser
    # `bool(results)` (which falls back to a live field read) — see the
    # docstring on `ArchivedBoardSummaryPayload.graded`.
    graded_ids = {s.tournament_id for s in await settlements.list_all()}
    return [
        ArchivedBoardSummaryPayload(
            tournament_id=s.tournament_id,
            tournament_name=s.tournament_name,
            tournament_start_date=s.tournament_start_date,
            source=s.source,
            out_of_sample=s.is_out_of_sample(date.fromisoformat(s.tournament_start_date)),
            graded=s.tournament_id in graded_ids,
        )
        for s in ordered
    ]


@router.get("/{tournament_id}")
async def predict_tournament(
    tournament_id: int,
    service: Annotated[PredictionService, Depends(get_prediction_service)],
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    board_archive: Annotated[BoardArchive, Depends(get_board_archive)],
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
    # Forward track record: capture this board immutably the first time it's
    # served for a not-yet-completed event, so the later grade is genuinely
    # pre-event. Best-effort — never let archival break serving.
    await _capture_board(catalog, board_archive, predictions)
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
        dg_direct_count=predictions.dg_direct_count,
        dg_fetch_status=predictions.dg_fetch_status.value,
    )
    if cache_enabled:
        await _store_board(cache_key, payload)
    return payload


@router.get("/{tournament_id}/archived")
async def archived_board(
    tournament_id: int,
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    board_archive: Annotated[BoardArchive, Depends(get_board_archive)],
    settlements: Annotated[SettlementArchive, Depends(get_settlement_archive)],
) -> ArchivedBoardPayload:
    """The pinned pre-event board for a tournament, straight from the ledger.

    Strictly read-only. It creates no board snapshot and pins no settlement:
    unlike the grader, which legitimately pins a result the first time it
    scores an event, this endpoint can be hit by anyone loading a page and
    must never write to an immutable archive as a side effect of a GET.

    Returns ``available: false`` rather than falling back to
    ``GET /predictions/{id}``. That endpoint recomputes with today's active
    model, which for an event inside the model's training window is an
    in-sample score — presenting it as the pre-event board is the specific
    defect this endpoint exists to remove.
    """
    tournament = await catalog.get_tournament(tournament_id)
    if tournament is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tournament {tournament_id} not found",
        )

    # The archive can hold several snapshots of one event (a retrain changes
    # the version id, and an event can be both captured and later backfilled).
    # Reuse the grader's own selection rule so this view cannot disagree with
    # the record about which board actually counts.
    snapshots = [s for s in await board_archive.list_all() if s.tournament_id == tournament_id]
    snapshot = canonical_by_tournament(snapshots).get(tournament_id)
    if snapshot is None:
        return ArchivedBoardPayload(
            available=False,
            tournament_id=tournament_id,
            tournament_name=tournament.name,
            tournament_start_date=tournament.start_date.isoformat(),
        )

    # Results, read-only. The pinned settlement is authoritative where one
    # exists; otherwise fall back to a live field read WITHOUT pinning it,
    # which is what keeps this endpoint free of write side effects.
    results: list[tuple[int, int | None, EntryStatus]] = []
    stored = await settlements.get(tournament_id)
    if stored is not None:
        for e in stored.entries:
            st = e.entry_status()
            if st is not None:
                results.append((e.player_id, e.final_position, st))
    else:
        field = await catalog.get_tournament_field(tournament_id)
        results = [(e.player_id, e.final_position, e.status) for e in field]

    had_a_cut = event_has_a_cut(st for _, _, st in results)
    result_by_player = {pid: (pos, st) for pid, pos, st in results}

    outcomes: list[ArchivedBoardOutcomePayload] = []
    for o in snapshot.outcomes:
        player = await catalog.get_player(o.player_id)
        pos, st = result_by_player.get(o.player_id, (None, None))
        outcomes.append(
            ArchivedBoardOutcomePayload(
                player_id=o.player_id,
                player_name=player.full_name if player else f"Player {o.player_id}",
                win_prob=o.win_prob,
                top_5_prob=o.top_5_prob,
                top_10_prob=o.top_10_prob,
                top_20_prob=o.top_20_prob,
                make_cut_prob=o.make_cut_prob,
                final_position=pos,
                # Withheld on a no-cut event: every player "made" a cut that
                # was never played, and reporting that as a result is the
                # contamination the grader excludes (2.3 / event_has_a_cut).
                made_cut=(st == EntryStatus.MADE_CUT) if (st is not None and had_a_cut) else None,
            )
        )

    return ArchivedBoardPayload(
        available=True,
        tournament_id=tournament_id,
        tournament_name=snapshot.tournament_name,
        tournament_start_date=snapshot.tournament_start_date,
        source=snapshot.source,
        as_of=snapshot.as_of,
        captured_at=snapshot.captured_at,
        model_name=snapshot.model_name,
        model_version_id=snapshot.model_version_id,
        model_trained_through=snapshot.model_trained_through,
        dg_direct_count=snapshot.dg_direct_count,
        dg_fetch_status=snapshot.dg_fetch_status,
        out_of_sample=snapshot.is_out_of_sample(tournament.start_date),
        graded=bool(results),
        event_had_a_cut=had_a_cut,
        outcomes=outcomes,
    )
