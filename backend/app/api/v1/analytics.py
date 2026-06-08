"""Analytics endpoints — model diagnostics for the ML lab page (doc 03)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.deps import get_model_registry, get_prediction_service
from app.api.v1.schemas import (
    BenchmarkPayload,
    BenchmarkPlayerRow,
    CalibrationReportPayload,
    OutcomeCalibrationPayload,
    ReliabilityBinPayload,
)
from app.config import get_settings
from app.ml.calibration import CalibratedOutcomeModel, ReliabilityBin
from app.ml.registry import ModelRegistry  # noqa: TC001 — FastAPI resolves at runtime
from app.services.predictions import PredictionService  # noqa: TC001

router = APIRouter(tags=["analytics"], prefix="/analytics")


def _bin_payload(b: ReliabilityBin) -> ReliabilityBinPayload:
    return ReliabilityBinPayload(
        lower=b.lower,
        upper=b.upper,
        mean_predicted=b.mean_predicted,
        observed_frequency=b.observed_frequency,
        count=b.count,
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
