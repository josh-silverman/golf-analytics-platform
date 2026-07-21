"""Analytics endpoints — model diagnostics for the ML lab page (doc 03)."""

from __future__ import annotations

from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.v1.deps import (
    get_board_archive,
    get_catalog_service,
    get_model_registry,
    get_prediction_service,
)
from app.api.v1.schemas import (
    BenchmarkPayload,
    BenchmarkPlayerRow,
    CalibrationReportPayload,
    ForwardBackfillEventPayload,
    ForwardBackfillPayload,
    ForwardMarketSkillPayload,
    ForwardTrackRecordPayload,
    OutcomeCalibrationPayload,
    ReliabilityBinPayload,
    TrackRecordPayload,
)
from app.config import get_settings
from app.domain.enums import TournamentStatus
from app.ml.calibration import CalibratedOutcomeModel, ReliabilityBin
from app.ml.registry import ModelRegistry  # noqa: TC001 — FastAPI resolves at runtime
from app.services.board_archive import (  # noqa: TC001
    BoardArchive,
    snapshot_from_predictions,
)
from app.services.catalog import CatalogService, reference_today  # noqa: TC001
from app.services.forward_track_record import compute_forward_track_record
from app.services.predictions import PredictionService  # noqa: TC001
from app.services.track_record import compute_track_record

# A completed OOS event more than this many days before today is old enough that
# re-checking it every backfill adds cost without value; the forward record is
# about *recent* served accuracy. Bounds the per-run work regardless of how much
# history the catalog returns.
_BACKFILL_LOOKBACK_DAYS = 120

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
        available=True, model_name=name, model_version_id=version, **data
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
) -> ForwardTrackRecordPayload:
    """Genuinely out-of-sample track record from captured pre-event boards.

    Grades only boards whose model was trained strictly before the event, so —
    unlike ``/track-record`` — it cannot be inflated by the active model having
    seen these events in training. Accumulates forward from the first captured
    pre-event board; ``available`` is false until one completed OOS board exists.
    """
    tr = await compute_forward_track_record(archive=archive, catalog=catalog)
    if tr is None:
        return ForwardTrackRecordPayload(available=False)
    return ForwardTrackRecordPayload(
        available=True,
        events=tr.events,
        players_graded=tr.players_graded,
        events_to_meaningful=tr.events_to_meaningful,
        markets=[
            ForwardMarketSkillPayload(
                market=m.market,
                n=m.n,
                base_rate=m.base_rate,
                brier=m.brier,
                brier_skill=m.brier_skill,
                ci_lower=m.ci_lower,
                ci_upper=m.ci_upper,
            )
            for m in tr.markets
        ],
    )


@router.post("/track-record/forward/backfill")
async def backfill_forward_track_record(
    service: Annotated[PredictionService, Depends(get_prediction_service)],
    catalog: Annotated[CatalogService, Depends(get_catalog_service)],
    archive: Annotated[BoardArchive, Depends(get_board_archive)],
    x_admin_token: Annotated[str | None, Header()] = None,
) -> ForwardBackfillPayload:
    """Seed the forward record from recent completed out-of-sample events.

    The live capture only records boards for events served *before* they
    complete, so events that finished before capture shipped are missing. This
    replays the exact served pipeline over each recent completed event — as-of
    capped to the eve, DataGolf's pre-event archive, no result leakage — and
    stores the resulting board immutably. Admitted only when the served model was
    trained strictly before the event, so every backfilled board is genuinely
    out-of-sample. Idempotent: an already-captured event is skipped.

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
        return ForwardBackfillPayload(examined=0, captured=0, skipped=0)

    floor = reference_today() - timedelta(days=_BACKFILL_LOOKBACK_DAYS)
    page = await catalog.list_tournaments(status=TournamentStatus.COMPLETED, limit=200)
    # Only events that (a) started after the model's cutoff → genuinely OOS, and
    # (b) are recent enough to matter. Newest first.
    candidates = sorted(
        (t for t in page.items if t.start_date > cutoff and t.start_date >= floor),
        key=lambda t: t.start_date,
        reverse=True,
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
            captured.append(ForwardBackfillEventPayload(tournament_id=t.id, name=t.name))
        else:
            skipped += 1

    return ForwardBackfillPayload(
        examined=len(candidates),
        captured=len(captured),
        skipped=skipped,
        events=captured,
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


@router.get("/benchmark/{tournament_id}")
async def get_benchmark(
    tournament_id: int,
    service: Annotated[PredictionService, Depends(get_prediction_service)],
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
) -> BenchmarkPayload:
    """Head-to-head: our model vs. DataGolf's published projections.

    When ``DATA_PROVIDER=mock`` the response sets ``dg_available=False`` and
    all ``dg_*`` fields are null — the frontend shows a "Connect DataGolf API"
    callout.

    When ``DATA_PROVIDER=datagolf`` the response fetches DataGolf's
    ``/preds/get-projections`` for the current field and aligns players by
    ``dg_id`` so the comparison is apples-to-apples.
    """
    from app.services.catalog import reference_today

    settings = get_settings()
    model_name = settings.active_model_name
    active = registry.get_active(model_name)
    model_version_id = active.version_id if active else None

    # Our predictions
    today = reference_today()
    predictions = await service.predict_tournament(tournament_id, as_of=today)
    if predictions is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Tournament {tournament_id} not found",
        )

    # DataGolf projections — only when using the real provider
    dg_available = settings.data_provider == "datagolf"
    dg_last_updated: str | None = None
    dg_by_dg_id: dict[int, dict[str, Any]] = {}

    if dg_available:
        try:
            from app.providers.datagolf.datagolf_provider import DataGolfProvider
            from app.providers.factory import get_data_provider

            provider = get_data_provider()
            # Unwrap CachingProviderWrapper if present
            raw_provider = getattr(provider, "_provider", provider)
            if isinstance(raw_provider, DataGolfProvider):
                projections = await raw_provider.get_dg_projections()
                for proj in projections:
                    dg_id = proj.get("dg_id")
                    if dg_id:
                        dg_by_dg_id[int(dg_id)] = proj
                if projections and isinstance(projections[0], dict):
                    dg_last_updated = projections[0].get("last_updated")
        except Exception:
            dg_available = False

    rows: list[BenchmarkPlayerRow] = []
    for outcome in predictions.outcomes:
        dg = dg_by_dg_id.get(outcome.player_id) if dg_available else None
        dg_win = (dg["win"] / 100.0) if dg and "win" in dg else None
        dg_top10 = (dg["top_10"] / 100.0) if dg and "top_10" in dg else None
        dg_cut = (dg["make_cut"] / 100.0) if dg and "make_cut" in dg else None
        win_diff = (outcome.win_prob - dg_win) if dg_win is not None else None

        rows.append(
            BenchmarkPlayerRow(
                player_id=outcome.player_id,
                player_name=outcome.player_name,
                our_win_prob=outcome.win_prob,
                our_top_10_prob=outcome.top_10_prob,
                our_make_cut_prob=outcome.make_cut_prob,
                dg_win_prob=dg_win,
                dg_top_10_prob=dg_top10,
                dg_make_cut_prob=dg_cut,
                win_diff=win_diff,
            )
        )

    # Sort: biggest absolute divergence first (most interesting comparisons up top)
    rows.sort(key=lambda r: abs(r.win_diff) if r.win_diff is not None else 0.0, reverse=True)

    return BenchmarkPayload(
        tournament_id=tournament_id,
        tournament_name=predictions.tournament_name,
        model_name=model_name,
        model_version_id=model_version_id,
        dg_available=dg_available,
        dg_last_updated=dg_last_updated,
        rows=rows,
    )
