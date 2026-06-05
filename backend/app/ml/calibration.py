"""Probability calibration — doc 01 §3 (Decision: calibration first-class), §4.

Raw classifier scores are not trustworthy probabilities: a model can rank
players well yet systematically over- or under-state how likely an outcome
is. Betting edge is the gap between model probability and implied
probability (doc 01 §1), so an uncalibrated model produces fake edges.
Isotonic regression fixes this by learning a monotone map from raw score to
observed frequency on a held-out set — "of the players we called 20% to
win, did ~20% actually win?"

The trainer fits the base classifier on an earlier slice and the isotonic
calibrators on a later, held-out slice (a time split, never random — see
``_time_split``), so the reported Brier and reliability numbers are honest
out-of-sample estimates rather than the optimistic in-sample figures the
base trainer records.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from sklearn.isotonic import IsotonicRegression

from app.ml.base import Model
from app.ml.trainer import LABEL_TO_OUTCOME_KEY, GBDTTrainer
from app.ml.training import TrainingData

if TYPE_CHECKING:
    from datetime import date

    from numpy.typing import NDArray

    from app.ml.registry import ModelRegistry, ModelVersion
    from app.ml.trainer import Trainer
    from app.ml.training import TrainingDataBuilder, TrainingExample


# A calibration set smaller than this can't produce meaningful reliability
# bins or a stable isotonic fit, so calibration is skipped and the base
# probabilities pass through unchanged.
_MIN_CALIBRATION_EXAMPLES = 30


@dataclass(frozen=True)
class ReliabilityBin:
    """One bucket of a reliability diagram.

    ``mean_predicted`` vs. ``observed_frequency`` is the diagonal a
    perfectly-calibrated model sits on; ``count`` weights the bucket so the
    frontend can de-emphasize near-empty bins.
    """

    lower: float
    upper: float
    mean_predicted: float
    observed_frequency: float
    count: int


@dataclass(frozen=True)
class OutcomeCalibration:
    """Calibration evidence for a single outcome (e.g. ``win_prob``)."""

    outcome_key: str
    brier_raw: float
    brier_calibrated: float
    bins_raw: tuple[ReliabilityBin, ...]
    bins_calibrated: tuple[ReliabilityBin, ...]


@dataclass(frozen=True)
class CalibrationReport:
    """Held-out calibration diagnostics for every outcome of a model."""

    outcomes: tuple[OutcomeCalibration, ...]
    n_calibration_examples: int


def brier_score(y_true: NDArray[np.float64], y_prob: NDArray[np.float64]) -> float:
    """Mean squared error between predicted probability and outcome."""
    return float(np.mean((y_prob - y_true) ** 2))


def reliability_bins(
    y_true: NDArray[np.float64],
    y_prob: NDArray[np.float64],
    *,
    n_bins: int = 10,
) -> tuple[ReliabilityBin, ...]:
    """Bucket predictions into ``n_bins`` equal-width probability bands.

    The last band is closed on the right so a prediction of exactly 1.0
    lands in it rather than falling off the end.
    """
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins: list[ReliabilityBin] = []
    for i in range(n_bins):
        lo, hi = float(edges[i]), float(edges[i + 1])
        if i == n_bins - 1:
            mask = (y_prob >= lo) & (y_prob <= hi)
        else:
            mask = (y_prob >= lo) & (y_prob < hi)
        count = int(mask.sum())
        if count == 0:
            mean_predicted = (lo + hi) / 2.0
            observed = 0.0
        else:
            mean_predicted = float(y_prob[mask].mean())
            observed = float(y_true[mask].mean())
        bins.append(
            ReliabilityBin(
                lower=lo,
                upper=hi,
                mean_predicted=mean_predicted,
                observed_frequency=observed,
                count=count,
            )
        )
    return tuple(bins)


class CalibratedOutcomeModel(Model):
    """Wraps a base model with per-outcome isotonic calibrators.

    ``predict`` runs the base model, then maps each raw probability through
    its calibrator (outcomes without a calibrator — e.g. a held-out set that
    was single-class — pass through unchanged). The held-out
    ``CalibrationReport`` rides along on the artifact so the diagnostics
    endpoint can serve reliability data without re-running training.
    """

    def __init__(
        self,
        *,
        base: Model,
        calibrators: dict[str, Any],
        report: CalibrationReport,
    ) -> None:
        self._base = base
        self._calibrators = calibrators
        self._report = report

    @property
    def report(self) -> CalibrationReport:
        return self._report

    def predict(self, features: dict[str, float]) -> dict[str, float]:
        raw = self._base.predict(features)
        calibrated: dict[str, float] = {}
        for outcome_key, value in raw.items():
            calibrator = self._calibrators.get(outcome_key)
            if calibrator is None:
                calibrated[outcome_key] = value
                continue
            mapped = float(calibrator.predict([value])[0])
            calibrated[outcome_key] = min(1.0, max(0.0, mapped))
        return calibrated


def _time_split(
    data: TrainingData, holdout_fraction: float
) -> tuple[list[TrainingExample], list[TrainingExample]]:
    """Chronological split: earliest examples train, latest calibrate.

    A random split would leak — calibrating on examples interleaved in time
    with training defeats the point. Holding out the most recent slice also
    mirrors deployment, where the model is always calibrated against the
    season's older events and applied to the newest.
    """
    ordered = sorted(
        data.examples, key=lambda e: (e.as_of, e.tournament_id, e.player_id)
    )
    n_holdout = int(len(ordered) * holdout_fraction)
    train = ordered[: len(ordered) - n_holdout]
    holdout = ordered[len(ordered) - n_holdout :]
    return train, holdout


@dataclass(frozen=True)
class CalibratedTrainingResult:
    """A calibrated model plus the metadata the registry records."""

    model: CalibratedOutcomeModel
    feature_names: tuple[str, ...]
    metrics: dict[str, float]
    hyperparameters: dict[str, Any]
    report: CalibrationReport


def fit_calibrated(
    base_trainer: Trainer,
    data: TrainingData,
    *,
    holdout_fraction: float = 0.25,
    n_bins: int = 10,
) -> CalibratedTrainingResult:
    """Fit a base model on the early slice, calibrate on the held-out slice.

    Falls back to identity calibration (base probabilities pass through)
    when the held-out set is too small to calibrate against, so the loop
    still produces a usable model on thin data.
    """
    if len(data) == 0:
        raise ValueError("Cannot calibrate on an empty dataset")

    train_examples, holdout_examples = _time_split(data, holdout_fraction)
    train_data = TrainingData(
        examples=tuple(train_examples),
        feature_set_hash=data.feature_set_hash,
        through_date=data.through_date,
    )
    base_result = base_trainer.fit(train_data)
    base_model = base_result.model

    metrics = dict(base_result.metrics)
    metrics["n_calibration_examples"] = float(len(holdout_examples))

    calibrators: dict[str, Any] = {}
    outcome_reports: list[OutcomeCalibration] = []

    can_calibrate = len(holdout_examples) >= _MIN_CALIBRATION_EXAMPLES
    raw_preds = (
        [base_model.predict(ex.features) for ex in holdout_examples]
        if can_calibrate
        else []
    )

    for label_key, outcome_key in LABEL_TO_OUTCOME_KEY.items():
        if not can_calibrate:
            continue
        y = np.array(
            [float(ex.labels[label_key]) for ex in holdout_examples],
            dtype=np.float64,
        )
        raw = np.array([rp[outcome_key] for rp in raw_preds], dtype=np.float64)

        single_class = bool(np.all(y == y[0]))
        if single_class:
            # Nothing to learn; leave this outcome uncalibrated.
            calibrated = raw
        else:
            calibrator = IsotonicRegression(
                out_of_bounds="clip", y_min=0.0, y_max=1.0
            )
            calibrator.fit(raw, y)
            calibrators[outcome_key] = calibrator
            calibrated = np.asarray(calibrator.predict(raw), dtype=np.float64)

        brier_raw = brier_score(y, raw)
        brier_cal = brier_score(y, calibrated)
        metrics[f"brier_holdout_raw_{outcome_key}"] = brier_raw
        metrics[f"brier_holdout_cal_{outcome_key}"] = brier_cal
        outcome_reports.append(
            OutcomeCalibration(
                outcome_key=outcome_key,
                brier_raw=brier_raw,
                brier_calibrated=brier_cal,
                bins_raw=reliability_bins(y, raw, n_bins=n_bins),
                bins_calibrated=reliability_bins(y, calibrated, n_bins=n_bins),
            )
        )

    report = CalibrationReport(
        outcomes=tuple(outcome_reports),
        n_calibration_examples=len(holdout_examples),
    )
    model = CalibratedOutcomeModel(
        base=base_model, calibrators=calibrators, report=report
    )
    return CalibratedTrainingResult(
        model=model,
        feature_names=base_result.feature_names,
        metrics=metrics,
        hyperparameters={**base_result.hyperparameters, "calibration": "isotonic"},
        report=report,
    )


async def train_calibrated_and_register(
    *,
    builder: TrainingDataBuilder,
    registry: ModelRegistry,
    through: date,
    name: str,
    base_trainer: Trainer | None = None,
    season: int | None = None,
    holdout_fraction: float = 0.25,
    activate: bool = True,
) -> ModelVersion:
    """Build a dataset, fit a calibrated model, and register/activate it.

    The calibrated counterpart of ``trainer.train_and_register`` — the
    ``/predictions`` endpoint picks up whichever version is active, so this
    is the path a real deploy should run to serve trustworthy probabilities.
    """
    base_trainer = base_trainer or GBDTTrainer()
    data = await builder.build(through=through, season=season)
    result = fit_calibrated(base_trainer, data, holdout_fraction=holdout_fraction)
    version = registry.register(
        name=name,
        model=result.model,
        feature_set_hash=data.feature_set_hash,
        training_data_through=data.through_date,
        hyperparameters=result.hyperparameters,
        metrics=result.metrics,
    )
    if activate:
        registry.set_active(name, version.version_id)
    return version
