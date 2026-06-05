"""Analytics endpoints — model diagnostics for the ML lab page (doc 03)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.v1.deps import get_model_registry
from app.api.v1.schemas import (
    CalibrationReportPayload,
    OutcomeCalibrationPayload,
    ReliabilityBinPayload,
)
from app.config import get_settings
from app.ml.calibration import CalibratedOutcomeModel, ReliabilityBin
from app.ml.registry import ModelRegistry  # noqa: TC001 — FastAPI resolves at runtime

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
