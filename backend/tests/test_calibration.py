"""Tests for isotonic calibration, reliability diagnostics, and the loop."""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

import numpy as np
import pytest

from app.ml.base import ConstantModel
from app.ml.calibration import (
    CalibratedOutcomeModel,
    CalibrationReport,
    brier_score,
    fit_calibrated,
    reliability_bins,
    train_calibrated_and_register,
)
from app.ml.registry import ModelRegistry
from app.ml.trainer import GBDTTrainer, TrainerConfig
from app.ml.training import TrainingData, TrainingExample

if TYPE_CHECKING:
    from pathlib import Path

_SMALL_DATA_CONFIG = TrainerConfig(max_iter=80, max_depth=2, min_samples_leaf=5)


def _labels(
    *,
    win: int = 0,
    top_5: int = 0,
    top_10: int = 0,
    top_20: int = 0,
    made_cut: int = 1,
) -> dict[str, int]:
    return {
        "win": win,
        "top_5": top_5,
        "top_10": top_10,
        "top_20": top_20,
        "made_cut": made_cut,
    }


def _separable_dataset(n: int = 160) -> TrainingData:
    """Strong players win, weak players miss the cut; spread over time so
    the chronological holdout split has both classes."""
    base = date(2026, 1, 1)
    examples: list[TrainingExample] = []
    for i in range(n):
        strong = i % 2 == 0
        examples.append(
            TrainingExample(
                player_id=i,
                tournament_id=i // 4,
                as_of=base + timedelta(days=i),
                features={"skill": 2.0 if strong else -2.0},
                labels=_labels(
                    win=1 if strong else 0,
                    top_5=1 if strong else 0,
                    top_10=1 if strong else 0,
                    top_20=1 if strong else 0,
                    made_cut=1 if strong else 0,
                ),
            )
        )
    return TrainingData(
        examples=tuple(examples),
        feature_set_hash="testhash",
        through_date=date(2026, 6, 1),
    )


# ---------------------------------------------------------------------------
# brier_score + reliability_bins
# ---------------------------------------------------------------------------


def test_brier_score_perfect_is_zero() -> None:
    y = np.array([1.0, 0.0, 1.0])
    assert brier_score(y, y) == 0.0


def test_brier_score_matches_manual() -> None:
    y = np.array([1.0, 0.0])
    p = np.array([0.8, 0.3])
    expected = ((0.8 - 1.0) ** 2 + (0.3 - 0.0) ** 2) / 2
    assert brier_score(y, p) == pytest.approx(expected)


def test_reliability_bins_count_covers_all_points() -> None:
    y = np.array([0.0, 1.0, 1.0, 0.0, 1.0])
    p = np.array([0.05, 0.95, 0.55, 0.15, 0.85])
    bins = reliability_bins(y, p, n_bins=10)
    assert len(bins) == 10
    assert sum(b.count for b in bins) == 5


def test_reliability_bins_prob_of_one_lands_in_last_bin() -> None:
    y = np.array([1.0])
    p = np.array([1.0])
    bins = reliability_bins(y, p, n_bins=10)
    assert bins[-1].count == 1
    assert bins[-1].observed_frequency == 1.0


def test_reliability_bins_observed_frequency_is_label_mean() -> None:
    # All predictions in one band; observed frequency = mean of labels.
    y = np.array([1.0, 0.0, 1.0, 1.0])
    p = np.array([0.52, 0.53, 0.54, 0.55])
    bins = reliability_bins(y, p, n_bins=10)
    band = next(b for b in bins if b.count == 4)
    assert band.observed_frequency == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# fit_calibrated
# ---------------------------------------------------------------------------


def test_fit_calibrated_produces_calibrated_model_with_report() -> None:
    result = fit_calibrated(GBDTTrainer(_SMALL_DATA_CONFIG), _separable_dataset())
    assert isinstance(result.model, CalibratedOutcomeModel)
    assert isinstance(result.report, CalibrationReport)
    assert result.report.n_calibration_examples > 0
    # One OutcomeCalibration per outcome key.
    assert {o.outcome_key for o in result.report.outcomes} == {
        "win_prob",
        "top_5_prob",
        "top_10_prob",
        "top_20_prob",
        "make_cut_prob",
    }


def test_calibrated_predictions_are_probabilities() -> None:
    result = fit_calibrated(GBDTTrainer(_SMALL_DATA_CONFIG), _separable_dataset())
    preds = result.model.predict({"skill": 2.0})
    assert all(0.0 <= p <= 1.0 for p in preds.values())


def test_hyperparameters_record_isotonic_calibration() -> None:
    result = fit_calibrated(GBDTTrainer(_SMALL_DATA_CONFIG), _separable_dataset())
    assert result.hyperparameters["calibration"] == "isotonic"


def test_metrics_include_holdout_brier_per_outcome() -> None:
    result = fit_calibrated(GBDTTrainer(_SMALL_DATA_CONFIG), _separable_dataset())
    for key in ("win_prob", "make_cut_prob"):
        assert f"brier_holdout_raw_{key}" in result.metrics
        assert f"brier_holdout_cal_{key}" in result.metrics


def test_fit_calibrated_empty_raises() -> None:
    empty = TrainingData(examples=(), feature_set_hash="h", through_date=date(2026, 1, 1))
    with pytest.raises(ValueError, match="empty dataset"):
        fit_calibrated(GBDTTrainer(), empty)


def test_thin_data_skips_calibration_but_still_builds_model() -> None:
    """Below the calibration-set threshold, the model passes base
    probabilities through and the report is empty rather than crashing."""
    data = _separable_dataset(n=40)  # 25% holdout = 10 < threshold (30)
    result = fit_calibrated(
        GBDTTrainer(_SMALL_DATA_CONFIG), data, holdout_fraction=0.25
    )
    assert isinstance(result.model, CalibratedOutcomeModel)
    assert result.report.outcomes == ()
    # Still predicts every outcome.
    assert len(result.model.predict({"skill": 2.0})) == 5


def test_uncalibrated_outcomes_pass_through_base() -> None:
    """An outcome with no calibrator returns the base probability verbatim."""
    base = ConstantModel({"win_prob": 0.42, "make_cut_prob": 0.7})
    report = CalibrationReport(outcomes=(), n_calibration_examples=0)
    model = CalibratedOutcomeModel(base=base, calibrators={}, report=report)
    assert model.predict({})["win_prob"] == 0.42


# ---------------------------------------------------------------------------
# train_calibrated_and_register
# ---------------------------------------------------------------------------


class _StubBuilder:
    def __init__(self, data: TrainingData) -> None:
        self._data = data

    async def build(
        self,
        *,
        through: date,
        season: int | None = None,
        page_size: int = 200,
    ) -> TrainingData:
        return self._data


async def test_train_calibrated_and_register_activates(tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path)
    version = await train_calibrated_and_register(
        builder=_StubBuilder(_separable_dataset()),  # type: ignore[arg-type]
        registry=registry,
        through=date(2026, 6, 1),
        name="golf_v1",
        base_trainer=GBDTTrainer(_SMALL_DATA_CONFIG),
    )

    active = registry.get_active("golf_v1")
    assert active is not None
    assert active.version_id == version.version_id
    assert version.hyperparameters["calibration"] == "isotonic"

    loaded = registry.load_artifact(active, model_cls=CalibratedOutcomeModel)
    assert isinstance(loaded, CalibratedOutcomeModel)
    assert loaded.report.n_calibration_examples > 0
    assert len(loaded.predict({"skill": 2.0})) == 5


async def test_calibrated_model_pickle_roundtrip_keeps_report(tmp_path: Path) -> None:
    result = fit_calibrated(GBDTTrainer(_SMALL_DATA_CONFIG), _separable_dataset())
    artifact = tmp_path / "artifact.pkl"
    result.model.save(artifact)
    loaded = CalibratedOutcomeModel.load(artifact)
    assert isinstance(loaded, CalibratedOutcomeModel)
    assert (
        loaded.report.n_calibration_examples
        == result.report.n_calibration_examples
    )
    assert loaded.predict({"skill": 2.0}) == result.model.predict({"skill": 2.0})
