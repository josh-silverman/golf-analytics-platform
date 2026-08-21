"""Analytics endpoints — model diagnostics for the ML lab page (doc 03)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.v1.deps import (
    get_board_archive,
    get_catalog_service,
    get_closing_line_archive,
    get_matchup_archive,
    get_model_registry,
    get_prediction_service,
    get_settlement_archive,
)
from app.api.v1.schemas import (
    ArchiveBoardSummaryPayload,
    ArchiveClosingLineSummaryPayload,
    ArchiveExportPayload,
    ArchiveImportPayload,
    ArchiveInspectPayload,
    ArchiveMatchupSummaryPayload,
    ArchiveSettlementSummaryPayload,
    BoardCaptureEventPayload,
    BoardCapturePayload,
    CalibrationReportPayload,
    ClosingLineCapturePayload,
    ClosingLineMarketPayload,
    ForwardBackfillEventPayload,
    ForwardBackfillPayload,
    ForwardMarketSkillPayload,
    ForwardTrackRecordPayload,
    MatchupCapturePayload,
    MatchupGradedEventPayload,
    MatchupLineRecordPayload,
    MatchupThresholdPayload,
    OutcomeCalibrationPayload,
    ReliabilityBinPayload,
    SettleEventPayload,
    SettlePayload,
    TrackRecordPayload,
)
from app.config import get_settings
from app.domain.enums import TournamentStatus
from app.ml.calibration import CalibratedOutcomeModel, ReliabilityBin
from app.ml.registry import ModelRegistry  # noqa: TC001 — FastAPI resolves at runtime
from app.providers.base import DataProvider  # noqa: TC001 — FastAPI DI
from app.providers.factory import get_data_provider
from app.services.archive_export import export_archives, import_archives
from app.services.board_archive import (  # noqa: TC001
    BoardArchive,
    snapshot_from_predictions,
)
from app.services.board_capture import CaptureOutcome, capture_pre_event_board
from app.services.catalog import CatalogService, reference_today  # noqa: TC001
from app.services.closing_line_archive import (
    ClosingLineArchive,  # noqa: TC001 — FastAPI DI
    OutrightFeedSource,
    capture_closing_lines,
)
from app.services.forward_track_record import (  # noqa: TC001
    MarketSkill,
    canonical_by_tournament,
    compute_forward_track_record,
)
from app.services.matchup_line_record import (
    MatchupArchive,  # noqa: TC001 — FastAPI DI
    MatchupHistorySource,
    compute_matchup_line_record,
    snapshot_from_feed,
)
from app.services.predictions import PredictionService  # noqa: TC001
from app.services.settlement_archive import SettlementArchive  # noqa: TC001 — FastAPI DI
from app.services.track_record import compute_track_record

# A completed OOS event more than this many days before today is old enough that
# re-checking it every backfill adds cost without value; the forward record is
# about *recent* served accuracy. Bounds the per-run work regardless of how much
# history the catalog returns.
_BACKFILL_LOOKBACK_DAYS = 120

# How far ahead a scheduled capture run looks. From a Wednesday run this is
# exactly this week's events (Thursday through Monday starts) without
# reaching into next week, where a board would be pinned before the field is
# settled — first write wins, so capturing too early is as permanent as
# capturing too late.
_CAPTURE_LOOKAHEAD_DAYS = 5

router = APIRouter(tags=["analytics"], prefix="/analytics")

# Track record is expensive (a field extraction per event) but only changes when
# events complete, so cache the aggregate for a week. Computed on first miss.
_TRACK_RECORD_TTL_S = 604_800  # 7 days


@router.get("/track-record")
async def get_track_record(
    service: Annotated[PredictionService, Depends(get_prediction_service)],
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
    events: int = 8,
) -> TrackRecordPayload:
    """Aggregate predicted-vs-actual accuracy over the last ``events`` completed
    tournaments (leakage-free pre-event boards). Cached for a week; the first
    request computes it.
    """
    import contextlib
    import json

    from app.cache.redis import redis_client

    events = max(1, min(events, 20))
    name = get_settings().active_model_name
    active = registry.get_active(name)
    version = active.version_id if active else None
    key = f"pga:track_record:{version}:{events}"

    try:
        raw = await redis_client.get(key)
    except Exception:  # noqa: BLE001 — cache is best-effort
        raw = None
    if raw:
        return TrackRecordPayload(
            available=True, model_name=name, model_version_id=version, **json.loads(raw)
        )

    tr = await compute_track_record(catalog=catalog, service=service, n_events=events)
    if tr is None:
        return TrackRecordPayload(available=False, model_name=name, model_version_id=version)

    data = {
        "events": tr.events,
        "players_graded": tr.players_graded,
        "winner_in_top10_rate": tr.winner_in_top10_rate,
        "mean_winner_rank": tr.mean_winner_rank,
        "avg_top20_hit_rate": tr.avg_top20_hit_rate,
        "make_cut_accuracy": tr.make_cut_accuracy,
    }
    with contextlib.suppress(Exception):
        await redis_client.setex(key, _TRACK_RECORD_TTL_S, json.dumps(data))
    return TrackRecordPayload(
        available=True,
        model_name=name,
        model_version_id=version,
        events=tr.events,
        players_graded=tr.players_graded,
        winner_in_top10_rate=tr.winner_in_top10_rate,
        mean_winner_rank=tr.mean_winner_rank,
        avg_top20_hit_rate=tr.avg_top20_hit_rate,
        make_cut_accuracy=tr.make_cut_accuracy,
    )


def _bin_payload(b: ReliabilityBin) -> ReliabilityBinPayload:
    return ReliabilityBinPayload(
        lower=b.lower,
        upper=b.upper,
        mean_predicted=b.mean_predicted,
        observed_frequency=b.observed_frequency,
        count=b.count,
    )


@router.get("/track-record/forward")
async def get_forward_track_record(
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    archive: Annotated[BoardArchive, Depends(get_board_archive)],
    settlements: Annotated[SettlementArchive, Depends(get_settlement_archive)],
) -> ForwardTrackRecordPayload:
    """Genuinely out-of-sample track record from captured pre-event boards.

    Grades only boards whose model was trained strictly before the event, so —
    unlike ``/track-record`` — it cannot be inflated by the active model having
    seen these events in training. Accumulates forward from the first captured
    pre-event board; ``available`` is false until one completed OOS board exists.
    """
    tr = await compute_forward_track_record(
        archive=archive, catalog=catalog, settlements=settlements
    )
    if tr is None:
        return ForwardTrackRecordPayload(available=False)
    return ForwardTrackRecordPayload(
        available=True,
        events=tr.events,
        players_graded=tr.players_graded,
        events_to_meaningful=tr.events_to_meaningful,
        events_path_a=tr.events_path_a,
        events_cold_start_only=tr.events_cold_start_only,
        events_regime_unknown=tr.events_regime_unknown,
        events_captured=tr.events_captured,
        events_backfilled=tr.events_backfilled,
        players_captured=tr.players_captured,
        players_backfilled=tr.players_backfilled,
        markets=_market_payloads(tr.markets),
        markets_captured=_market_payloads(tr.markets_captured),
        markets_backfilled=_market_payloads(tr.markets_backfilled),
    )


def _market_payloads(markets: tuple[MarketSkill, ...]) -> list[ForwardMarketSkillPayload]:
    return [
        ForwardMarketSkillPayload(
            market=m.market,
            n=m.n,
            base_rate=m.base_rate,
            brier=m.brier,
            brier_skill=m.brier_skill,
            ci_lower=m.ci_lower,
            ci_upper=m.ci_upper,
        )
        for m in markets
    ]


@router.post("/track-record/settle")
async def settle_and_grade(
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    archive: Annotated[BoardArchive, Depends(get_board_archive)],
    settlements: Annotated[SettlementArchive, Depends(get_settlement_archive)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> SettlePayload:
    """Pin results for newly completed events and regrade the forward record.

    Settling is a side effect of grading (§2.4 of ``docs/ledger.md``): the
    grader writes an immutable ``SettlementRecord`` for any completed,
    out-of-sample event that lacks one. That already happens on any request
    to ``/track-record/forward``, so this endpoint does not add capability —
    it makes the timing deterministic, the same reason scheduled capture
    exists, and reports which events were newly pinned.

    Idempotent by construction: settlements are first-write-wins, so a
    second run for the same event pins nothing and reports no new events.

    Cost is proportional to the number of *newly* completed events, not to
    the size of the record: an event that already has a settlement is graded
    without touching the provider at all.

    Admin-gated: requires ``X-Admin-Token`` matching
    ``settings.admin_api_token``; 404 when the secret is unset.
    """
    token = get_settings().admin_api_token
    if not token or x_admin_token != token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    before = {r.tournament_id for r in await settlements.list_all()}
    tr = await compute_forward_track_record(
        archive=archive, catalog=catalog, settlements=settlements
    )
    after = await settlements.list_all()

    return SettlePayload(
        available=tr is not None,
        events_graded=tr.events if tr is not None else 0,
        settlements_total=len(after),
        newly_settled=[
            SettleEventPayload(
                tournament_id=r.tournament_id,
                name=r.tournament_name,
                start_date=r.tournament_start_date,
                players=len(r.entries),
            )
            for r in sorted(after, key=lambda r: r.tournament_start_date)
            if r.tournament_id not in before
        ],
    )


@router.post("/track-record/capture-upcoming")
async def capture_upcoming_boards(
    service: Annotated[PredictionService, Depends(get_prediction_service)],
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    archive: Annotated[BoardArchive, Depends(get_board_archive)],
    x_admin_token: Annotated[str | None, Header()] = None,
    days_ahead: int = _CAPTURE_LOOKAHEAD_DAYS,
) -> BoardCapturePayload:
    """Capture pre-event boards for every upcoming event starting soon.

    Makes capture timing deterministic instead of depending on someone
    loading the leaderboard before the event (see ``docs/ledger.md`` §3.6).
    Called by the Wednesday cron in ``.github/workflows/board-capture.yml``.

    Covers *every* upcoming event inside the window rather than a single
    "current event": opposite-field weeks put two tournaments on the same
    dates, and ``get_current_tournament`` returns one of them (preferring an
    in-progress event, which is precisely the one that must not be
    captured), so a single-event job would never capture the second.

    Idempotent: an event with a snapshot for the serving model version is
    reported ``already_captured`` and nothing is written. Every write goes
    through the shared start guard in ``services/board_capture``, so an
    event that has already begun is refused rather than pinned.

    Admin-gated: requires ``X-Admin-Token`` matching
    ``settings.admin_api_token``; 404 when the secret is unset.
    """
    token = get_settings().admin_api_token
    if not token or x_admin_token != token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    days_ahead = max(1, min(days_ahead, 30))
    today = reference_today()
    horizon = today + timedelta(days=days_ahead)
    page = await catalog.list_tournaments(status=TournamentStatus.UPCOMING, limit=200)
    # Strictly after today: the start guard refuses a same-day capture, so
    # listing such an event here would only produce a guaranteed refusal.
    candidates = sorted(
        (t for t in page.items if today < t.start_date <= horizon),
        key=lambda t: t.start_date,
    )

    events: list[BoardCaptureEventPayload] = []
    for t in candidates:
        preds = await service.predict_tournament(t.id, as_of=today)
        if preds is None:
            events.append(
                BoardCaptureEventPayload(
                    tournament_id=t.id,
                    name=t.name,
                    start_date=t.start_date,
                    outcome=CaptureOutcome.TOURNAMENT_NOT_FOUND.value,
                )
            )
            continue
        outcome = await capture_pre_event_board(
            catalog=catalog, archive=archive, predictions=preds, today=today
        )
        events.append(
            BoardCaptureEventPayload(
                tournament_id=t.id,
                name=t.name,
                start_date=t.start_date,
                outcome=outcome.value,
                outcomes_captured=len(preds.outcomes),
            )
        )

    return BoardCapturePayload(
        examined=len(candidates),
        captured=sum(1 for e in events if e.outcome == CaptureOutcome.CAPTURED.value),
        # An empty window (an off week) is healthy; a listed event that did
        # not end up with a board is not.
        healthy=all(CaptureOutcome(e.outcome).is_healthy for e in events),
        events=events,
    )


@router.post("/track-record/forward/backfill")
async def backfill_forward_track_record(
    service: Annotated[PredictionService, Depends(get_prediction_service)],
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    archive: Annotated[BoardArchive, Depends(get_board_archive)],
    x_admin_token: Annotated[str | None, Header()] = None,
    dry_run: bool = False,
) -> ForwardBackfillPayload:
    """Seed the forward record from recent completed out-of-sample events.

    The live capture only records boards for events served *before* they
    complete, so events that finished before capture shipped are missing. This
    replays the exact served pipeline over each recent completed event — as-of
    capped to the eve, DataGolf's pre-event archive, no result leakage — and
    stores the resulting board immutably. Admitted only when the served model was
    trained strictly before the event, so every backfilled board is genuinely
    out-of-sample. Idempotent: an already-captured event is skipped.

    ``?dry_run=true`` writes nothing and returns the candidate list instead:
    which events are in scope, when they started, and which already have a
    snapshot. It runs only the cheap checks (OOS cutoff, lookback window,
    ``archive.has``) and never builds a board, so it answers "what would this
    reconstruct?" in one fast call rather than by hand-deriving the window from
    the source. A real run can still skip a listed candidate that turns out to
    have no field or an uncertifiable cutoff once its board is built.

    Admin-gated: requires the ``X-Admin-Token`` header to match
    ``settings.admin_api_token``. When that setting is unset the endpoint is
    disabled and returns 404, so it never exists in an unconfigured deployment.
    """
    token = get_settings().admin_api_token
    if not token or x_admin_token != token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    cutoff = service.model_trained_through
    if cutoff is None:
        # Served model has no known training cutoff → nothing can be certified OOS.
        return ForwardBackfillPayload(examined=0, captured=0, skipped=0, dry_run=dry_run)

    floor = reference_today() - timedelta(days=_BACKFILL_LOOKBACK_DAYS)
    page = await catalog.list_tournaments(status=TournamentStatus.COMPLETED, limit=200)
    # Only events that (a) started after the model's cutoff → genuinely OOS, and
    # (b) are recent enough to matter. Newest first.
    candidates = sorted(
        (t for t in page.items if t.start_date > cutoff and t.start_date >= floor),
        key=lambda t: t.start_date,
        reverse=True,
    )

    if dry_run:
        # Cheap checks only: never build a board, never write. Lists every
        # candidate so the reader sees the full window, with the ones a real
        # run would skip flagged rather than omitted.
        listed: list[ForwardBackfillEventPayload] = []
        already = 0
        for t in candidates:
            has_snapshot = service.model_version_id is not None and await archive.has(
                t.id, service.model_version_id
            )
            already += 1 if has_snapshot else 0
            listed.append(
                ForwardBackfillEventPayload(
                    tournament_id=t.id,
                    name=t.name,
                    start_date=t.start_date,
                    already_captured=has_snapshot,
                )
            )
        return ForwardBackfillPayload(
            examined=len(candidates),
            captured=0,
            skipped=already,
            events=listed,
            dry_run=True,
        )

    captured: list[ForwardBackfillEventPayload] = []
    skipped = 0
    for t in candidates:
        if service.model_version_id is not None and await archive.has(
            t.id, service.model_version_id
        ):
            # Cheap pre-check before the expensive board build. persist()'s NX
            # guarantee is the real correctness boundary; this just skips already-
            # captured events on an idempotent re-run without rebuilding a board.
            skipped += 1
            continue
        preds = await service.predict_tournament(t.id, as_of=reference_today())
        if (
            preds is None
            or preds.model_trained_through is None
            or not preds.outcomes
            or preds.model_trained_through >= t.start_date
            or await archive.has(t.id, preds.model_version_id)
        ):
            skipped += 1
            continue
        snapshot = snapshot_from_predictions(
            preds,
            tournament_start_date=t.start_date,
            model_trained_through=preds.model_trained_through,
            source="backfilled",
        )
        if await archive.persist(snapshot):
            captured.append(
                ForwardBackfillEventPayload(
                    tournament_id=t.id, name=t.name, start_date=t.start_date
                )
            )
        else:
            skipped += 1

    return ForwardBackfillPayload(
        examined=len(candidates),
        captured=len(captured),
        skipped=skipped,
        events=captured,
    )


@router.post("/matchups/capture")
async def capture_matchup_lines(
    provider: Annotated[DataProvider, Depends(get_data_provider)],
    archive: Annotated[MatchupArchive, Depends(get_matchup_archive)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> MatchupCapturePayload:
    """Capture this week's matchup board: every book's price on every 2-way
    tournament matchup plus DataGolf's own line, stored immutably per event.

    Called by a weekly scheduled job before the Thursday tee-off. First capture
    wins — a re-run (the Thursday retry, a manual trigger) never overwrites, so
    the later grade provably reflects pre-event prices. The graded record lives
    at ``GET /analytics/matchups/line-record``.

    Admin-gated exactly like the forward backfill: requires ``X-Admin-Token``
    matching ``settings.admin_api_token``; 404 when the secret is unset, 409
    when the configured provider has no live matchup feed (mock).
    """
    token = get_settings().admin_api_token
    if not token or x_admin_token != token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    fetch = getattr(provider, "fetch_live_matchups", None)
    if fetch is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configured data provider has no live matchup feed",
        )

    feed = await fetch()
    snapshot = snapshot_from_feed(feed, year=reference_today().year)
    if snapshot is None:
        return MatchupCapturePayload(captured=False, detail="no matchup board this week")
    stored = await archive.persist(snapshot)
    return MatchupCapturePayload(
        captured=stored,
        event_name=snapshot.event_name,
        year=snapshot.year,
        matchups=len(snapshot.rows),
        detail="stored" if stored else "already captured",
    )


@router.post("/closing-lines/capture")
async def capture_closing_line_board(
    provider: Annotated[DataProvider, Depends(get_data_provider)],
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    archive: Annotated[ClosingLineArchive, Depends(get_closing_line_archive)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> ClosingLineCapturePayload:
    """Capture this week's outright market immutably, before the event starts.

    Snapshots every book's price across all five markets, plus DataGolf's own
    baseline line, as the named market baseline the forward record will be
    graded against (A4b). Called by the Wednesday cron in
    ``.github/workflows/closing-line-capture.yml``.

    Refuses to write for an event that has already begun, for the same reason
    board capture does (``docs/ledger.md`` §2.2): DataGolf keeps serving
    outrights during play, in-play prices are not marked as such, and first
    capture wins, so a late snapshot is pinned forever as if it were
    pre-event. Idempotent — a second run for the same event writes nothing
    and reports ``already_captured``.

    Admin-gated exactly like the matchup capture: requires ``X-Admin-Token``
    matching ``settings.admin_api_token``; 404 when the secret is unset, 409
    when the configured provider has no outright feed (mock).
    """
    token = get_settings().admin_api_token
    if not token or x_admin_token != token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    if not hasattr(provider, "fetch_live_outrights"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Configured data provider has no outright odds feed",
        )

    result = await capture_closing_lines(
        catalog=catalog,
        archive=archive,
        # hasattr above is the runtime capability gate; mypy can't narrow a
        # nominal DataProvider to the structural protocol from it.
        source=cast("OutrightFeedSource", provider),
        today=reference_today(),
    )
    return ClosingLineCapturePayload(
        outcome=result.outcome.value,
        healthy=result.outcome.is_healthy,
        event_name=result.event_name,
        year=result.year,
        tournament_id=result.tournament_id,
        tournament_start_date=result.tournament_start_date,
        markets_offered=result.markets_offered,
        players=result.players,
    )


@router.get("/matchups/line-record")
async def get_matchup_line_record(
    provider: Annotated[DataProvider, Depends(get_data_provider)],
    archive: Annotated[MatchupArchive, Depends(get_matchup_archive)],
) -> MatchupLineRecordPayload:
    """Forward record of DataGolf's matchup line against real book prices.

    Grades every captured pre-event snapshot whose event has settled in the
    historical-odds archive: would betting the sides DataGolf's de-vigged line
    called +EV have made money? The 2019-2026 backtest could not answer this
    (the archive never stored DataGolf's line); this record is the evidence
    that decides whether a matchup surface may ever present an edge claim.
    ``available`` is false until the first capture exists.
    """
    if not hasattr(provider, "fetch_historical_matchup_event_list"):
        return MatchupLineRecordPayload(available=False)
    # The hasattr check above is the runtime capability gate; mypy can't narrow
    # a nominal DataProvider to the structural protocol from it, hence the cast.
    record = await compute_matchup_line_record(archive, cast("MatchupHistorySource", provider))
    if record is None:
        return MatchupLineRecordPayload(available=False)

    def _thresholds(records: tuple) -> list[MatchupThresholdPayload]:  # type: ignore[type-arg]
        return [
            MatchupThresholdPayload(min_edge=t.min_edge, bets=t.bets, pnl=t.pnl, roi=t.roi)
            for t in records
        ]

    return MatchupLineRecordPayload(
        available=True,
        events_captured=record.events_captured,
        events_graded=record.events_graded,
        events_pending=record.events_pending,
        matchups_graded=record.matchups_graded,
        dg_line_brier=record.dg_line_brier,
        dg_line_n=record.dg_line_n,
        any_price=_thresholds(record.any_price),
        best_price=_thresholds(record.best_price),
        events=[
            MatchupGradedEventPayload(
                event_name=e.event_name,
                year=e.year,
                matchups_captured=e.matchups_captured,
                matchups_graded=e.matchups_graded,
                bets=e.bets,
                pnl=e.pnl,
            )
            for e in record.events
        ],
    )


@router.get("/archive/export")
async def export_archive(
    board_archive: Annotated[BoardArchive, Depends(get_board_archive)],
    matchup_archive: Annotated[MatchupArchive, Depends(get_matchup_archive)],
    settlement_archive: Annotated[SettlementArchive, Depends(get_settlement_archive)],
    closing_line_archive: Annotated[ClosingLineArchive, Depends(get_closing_line_archive)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> ArchiveExportPayload:
    """Dump both forward archives (board + matchup snapshots) as one document.

    The production archives live in a Key Value instance with no persistence,
    so this is the ledger's survival mechanism: a scheduled job fetches this
    dump and commits it to a **private** repository (the content is
    DataGolf-derived — personal use only, never the public repo). Output is
    deterministic for an unchanged archive, so that job can skip empty
    commits, and the resulting git history independently witnesses that each
    prediction existed before its event.

    Admin-gated like the backfill: requires ``X-Admin-Token`` matching
    ``settings.admin_api_token``; 404 when the secret is unset.
    """
    token = get_settings().admin_api_token
    if not token or x_admin_token != token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    doc = await export_archives(
        boards=board_archive,
        matchups=matchup_archive,
        settlements=settlement_archive,
        closing_lines=closing_line_archive,
    )
    return ArchiveExportPayload.model_validate(doc)


@router.get("/archive/inspect")
async def inspect_archive(
    board_archive: Annotated[BoardArchive, Depends(get_board_archive)],
    matchup_archive: Annotated[MatchupArchive, Depends(get_matchup_archive)],
    settlement_archive: Annotated[SettlementArchive, Depends(get_settlement_archive)],
    closing_line_archive: Annotated[ClosingLineArchive, Depends(get_closing_line_archive)],
    x_admin_token: Annotated[str | None, Header()] = None,
    tournament_id: int | None = None,
) -> ArchiveInspectPayload:
    """What the archives actually hold, as metadata rather than a full dump.

    The debugging counterpart to ``/archive/export``: when an event is missing
    from the forward record, this says whether a snapshot exists, whether its
    model can certify it out-of-sample, and whether it is the one the grader
    picks for that tournament (several snapshots per event are normal after a
    retrain). Probabilities and prices are omitted, both to keep the response
    small and to keep DataGolf-derived numbers out of workflow logs.

    Optional ``?tournament_id=`` narrows the board list to one event. Whether
    the event has completed is not answered here; that needs the catalog.

    Admin-gated like the export, and read-only: it writes nothing.
    """
    token = get_settings().admin_api_token
    if not token or x_admin_token != token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    boards = await board_archive.list_all()
    canonical = canonical_by_tournament(boards)
    selected = [b for b in boards if tournament_id is None or b.tournament_id == tournament_id]
    selected.sort(key=lambda b: (b.tournament_start_date, b.captured_at))

    board_payloads = [
        ArchiveBoardSummaryPayload(
            tournament_id=b.tournament_id,
            tournament_name=b.tournament_name,
            tournament_start_date=b.tournament_start_date,
            model_name=b.model_name,
            model_version_id=b.model_version_id,
            model_trained_through=b.model_trained_through,
            as_of=b.as_of,
            captured_at=b.captured_at,
            source=b.source,
            outcomes=len(b.outcomes),
            dg_direct_count=b.dg_direct_count,
            dg_baseline=len(b.dg_baseline) if b.dg_baseline is not None else None,
            out_of_sample=b.is_out_of_sample(date.fromisoformat(b.tournament_start_date)),
            canonical=canonical.get(b.tournament_id) is b,
        )
        for b in selected
    ]

    matchups = await matchup_archive.list_all()
    matchups.sort(key=lambda m: (m.year, m.captured_at))

    all_settlements = await settlement_archive.list_all()
    settlements = [
        s for s in all_settlements if tournament_id is None or s.tournament_id == tournament_id
    ]
    settlements.sort(key=lambda s: s.tournament_start_date)
    settlement_payloads = []
    for s in settlements:
        made = sum(1 for e in s.entries if e.status == "made_cut")
        missed = sum(1 for e in s.entries if e.status == "missed_cut")
        settlement_payloads.append(
            ArchiveSettlementSummaryPayload(
                tournament_id=s.tournament_id,
                tournament_name=s.tournament_name,
                tournament_start_date=s.tournament_start_date,
                provider=s.provider,
                settled_at=s.settled_at,
                players=len(s.entries),
                made_cut=made,
                missed_cut=missed,
                other=len(s.entries) - made - missed,
            )
        )

    closing = await closing_line_archive.list_all()
    closing.sort(key=lambda c: (c.year, c.captured_at))

    return ArchiveInspectPayload(
        boards=len(boards),
        matchups=len(matchups),
        settlements=len(all_settlements),
        closing_lines=len(closing),
        board_snapshots=board_payloads,
        matchup_snapshots=[
            ArchiveMatchupSummaryPayload(
                event_name=m.event_name,
                year=m.year,
                market=m.market,
                captured_at=m.captured_at,
                rows=len(m.rows),
            )
            for m in matchups
        ],
        settlement_records=settlement_payloads,
        closing_line_snapshots=[
            ArchiveClosingLineSummaryPayload(
                event_name=c.event_name,
                year=c.year,
                tournament_id=c.tournament_id,
                tournament_start_date=c.tournament_start_date,
                captured_at=c.captured_at,
                markets=[
                    ClosingLineMarketPayload(
                        market=m.market,
                        offered=m.offered,
                        players=len(m.lines),
                        books=len(m.books_offering),
                        detail=m.detail,
                    )
                    for m in c.markets
                ],
            )
            for c in closing
        ],
    )


@router.post("/archive/import")
async def import_archive(
    payload: ArchiveExportPayload,
    board_archive: Annotated[BoardArchive, Depends(get_board_archive)],
    matchup_archive: Annotated[MatchupArchive, Depends(get_matchup_archive)],
    settlement_archive: Annotated[SettlementArchive, Depends(get_settlement_archive)],
    closing_line_archive: Annotated[ClosingLineArchive, Depends(get_closing_line_archive)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> ArchiveImportPayload:
    """Restore both forward archives from an export dump.

    The disaster-recovery half of ``/archive/export``: after a Key Value
    wipe, POST the last committed dump and the record is back. Idempotent
    and safe against races by construction — snapshots are written through
    the archives' first-write-wins ``persist``, so an import can only fill
    gaps, never overwrite a snapshot the live store still holds.

    Admin-gated identically to the export.
    """
    token = get_settings().admin_api_token
    if not token or x_admin_token != token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

    result = await import_archives(
        payload.model_dump(),
        boards=board_archive,
        matchups=matchup_archive,
        settlements=settlement_archive,
        closing_lines=closing_line_archive,
    )
    return ArchiveImportPayload(
        boards_stored=result.boards_stored,
        boards_skipped=result.boards_skipped,
        boards_errors=result.boards_errors,
        matchups_stored=result.matchups_stored,
        matchups_skipped=result.matchups_skipped,
        matchups_errors=result.matchups_errors,
        settlements_stored=result.settlements_stored,
        settlements_skipped=result.settlements_skipped,
        settlements_errors=result.settlements_errors,
        closing_lines_stored=result.closing_lines_stored,
        closing_lines_skipped=result.closing_lines_skipped,
        closing_lines_errors=result.closing_lines_errors,
    )


@router.get("/calibration")
async def get_calibration(
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
) -> CalibrationReportPayload:
    """Held-out reliability diagnostics for the active model.

    404 when no model is registered (the predictions endpoint is serving the
    ConstantModel fallback); 409 when the active model carries no calibration
    data (e.g. trained without the calibration step).
    """
    name = get_settings().active_model_name
    active = registry.get_active(name)
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active model registered",
        )
    model = registry.load_artifact(active)
    if not isinstance(model, CalibratedOutcomeModel):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Active model has no calibration data",
        )

    report = model.report
    return CalibrationReportPayload(
        model_name=name,
        model_version_id=active.version_id,
        n_calibration_examples=report.n_calibration_examples,
        outcomes=[
            OutcomeCalibrationPayload(
                outcome_key=o.outcome_key,
                brier_raw=o.brier_raw,
                brier_calibrated=o.brier_calibrated,
                bins_raw=[_bin_payload(b) for b in o.bins_raw],
                bins_calibrated=[_bin_payload(b) for b in o.bins_calibrated],
            )
            for o in report.outcomes
        ],
    )
