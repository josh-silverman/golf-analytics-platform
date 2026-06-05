"""Tests for the GBDT trainer, outcome model, and train→register loop."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from app.ml.registry import ModelRegistry
from app.ml.trainer import (
    LABEL_TO_OUTCOME_KEY,
    GBDTOutcomeModel,
    GBDTTrainer,
    TrainerConfig,
    train_and_register,
)
from app.ml.training import TrainingData, TrainingExample

if TYPE_CHECKING:
    from pathlib import Path

_OUTCOME_KEYS = set(LABEL_TO_OUTCOME_KEY.values())


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


def _example(
    *,
    features: dict[str, float],
    labels: dict[str, int],
    pid: int = 1,
    tid: int = 1,
) -> TrainingExample:
    return TrainingExample(
        player_id=pid,
        tournament_id=tid,
        as_of=date(2026, 1, 1),
        features=features,
        labels=labels,
    )


def _dataset(examples: list[TrainingExample]) -> TrainingData:
    return TrainingData(
        examples=tuple(examples),
        feature_set_hash="testhash",
        through_date=date(2026, 1, 1),
    )


def _separable_dataset(n: int = 60) -> TrainingData:
    """Half the field is strong (wins), half weak (misses cut).

    A single feature ``skill`` cleanly separates the two groups so a fitted
    classifier should rank a strong player above a weak one.
    """
    examples: list[TrainingExample] = []
    for i in range(n):
        strong = i % 2 == 0
        examples.append(
            _example(
                features={"skill": 2.0 if strong else -2.0},
                labels=_labels(
                    win=1 if strong else 0,
                    top_5=1 if strong else 0,
                    top_10=1 if strong else 0,
                    top_20=1 if strong else 0,
                    made_cut=1 if strong else 0,
                ),
                pid=i,
            )
        )
    return _dataset(examples)


# A config that splits on small synthetic datasets (defaults need 20/leaf).
_SMALL_DATA_CONFIG = TrainerConfig(max_iter=80, max_depth=2, min_samples_leaf=5)


# ---------------------------------------------------------------------------
# GBDTTrainer.fit
# ---------------------------------------------------------------------------


def test_fit_produces_model_predicting_every_outcome_key() -> None:
    trainer = GBDTTrainer(_SMALL_DATA_CONFIG)
    result = trainer.fit(_separable_dataset())

    preds = result.model.predict({"skill": 2.0})
    assert set(preds.keys()) == _OUTCOME_KEYS
    assert all(0.0 <= p <= 1.0 for p in preds.values())


def test_model_ranks_strong_player_above_weak() -> None:
    trainer = GBDTTrainer(_SMALL_DATA_CONFIG)
    result = trainer.fit(_separable_dataset())

    strong = result.model.predict({"skill": 2.0})
    weak = result.model.predict({"skill": -2.0})
    assert strong["win_prob"] > weak["win_prob"]
    assert strong["make_cut_prob"] > weak["make_cut_prob"]


def test_fit_on_empty_dataset_raises() -> None:
    trainer = GBDTTrainer()
    with pytest.raises(ValueError, match="empty dataset"):
        trainer.fit(_dataset([]))


def test_degenerate_outcome_returns_constant_zero() -> None:
    """No example ever won, so the win classifier sees a single class.

    It must return 0.0 for any input rather than crashing on a missing
    positive-class column.
    """
    examples = [
        _example(
            features={"skill": float(i)},
            labels=_labels(win=0, made_cut=1),
            pid=i,
        )
        for i in range(30)
    ]
    result = GBDTTrainer(_SMALL_DATA_CONFIG).fit(_dataset(examples))

    assert result.model.predict({"skill": 99.0})["win_prob"] == 0.0
    # made_cut was always 1 → constant 1.0.
    assert result.model.predict({"skill": -99.0})["make_cut_prob"] == 1.0


def test_feature_names_are_sorted_union_across_examples() -> None:
    examples = [
        _example(features={"b": 1.0, "a": 1.0}, labels=_labels(made_cut=1), pid=1),
        _example(features={"c": 1.0}, labels=_labels(made_cut=0), pid=2),
    ]
    # Pad so the classifier has enough rows to fit without error.
    examples += [
        _example(features={"a": 0.0}, labels=_labels(made_cut=1), pid=i)
        for i in range(3, 25)
    ]
    result = GBDTTrainer(_SMALL_DATA_CONFIG).fit(_dataset(examples))
    assert result.feature_names == ("a", "b", "c")


def test_metrics_record_brier_per_outcome_and_dataset_shape() -> None:
    data = _separable_dataset()
    result = GBDTTrainer(_SMALL_DATA_CONFIG).fit(data)

    for outcome_key in _OUTCOME_KEYS:
        assert f"brier_{outcome_key}" in result.metrics
    assert result.metrics["n_examples"] == float(len(data))
    assert result.metrics["n_features"] == 1.0


def test_unknown_features_default_to_zero_no_crash() -> None:
    result = GBDTTrainer(_SMALL_DATA_CONFIG).fit(_separable_dataset())
    # Feature the model never saw plus a missing trained feature.
    preds = result.model.predict({"unseen": 5.0})
    assert set(preds.keys()) == _OUTCOME_KEYS


def test_hyperparameters_identify_model_family() -> None:
    hp = GBDTTrainer().hyperparameters
    assert hp["model_family"] == "sklearn.HistGradientBoostingClassifier"
    assert "max_iter" in hp


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_model_pickle_roundtrip_preserves_predictions(tmp_path: Path) -> None:
    result = GBDTTrainer(_SMALL_DATA_CONFIG).fit(_separable_dataset())
    before = result.model.predict({"skill": 2.0})

    artifact = tmp_path / "artifact.pkl"
    result.model.save(artifact)
    loaded = GBDTOutcomeModel.load(artifact)

    assert isinstance(loaded, GBDTOutcomeModel)
    assert loaded.predict({"skill": 2.0}) == before


# ---------------------------------------------------------------------------
# train_and_register
# ---------------------------------------------------------------------------


class _StubBuilder:
    """Returns a fixed dataset; records the args it was called with."""

    def __init__(self, data: TrainingData) -> None:
        self._data = data
        self.calls: list[tuple[date, int | None]] = []

    async def build(
        self,
        *,
        through: date,
        season: int | None = None,
        page_size: int = 200,
    ) -> TrainingData:
        self.calls.append((through, season))
        return self._data


async def test_train_and_register_registers_and_activates(tmp_path: Path) -> None:
    builder = _StubBuilder(_separable_dataset())
    registry = ModelRegistry(tmp_path)

    version = await train_and_register(
        builder=builder,  # type: ignore[arg-type]
        registry=registry,
        through=date(2026, 5, 1),
        name="golf_v1",
        trainer=GBDTTrainer(_SMALL_DATA_CONFIG),
    )

    active = registry.get_active("golf_v1")
    assert active is not None
    assert active.version_id == version.version_id
    assert version.feature_set_hash == "testhash"
    assert version.training_data_through == date(2026, 1, 1)
    assert builder.calls == [(date(2026, 5, 1), None)]

    loaded = registry.load_artifact(version, model_cls=GBDTOutcomeModel)
    assert set(loaded.predict({"skill": 2.0}).keys()) == _OUTCOME_KEYS


async def test_train_and_register_can_skip_activation(tmp_path: Path) -> None:
    builder = _StubBuilder(_separable_dataset())
    registry = ModelRegistry(tmp_path)

    await train_and_register(
        builder=builder,  # type: ignore[arg-type]
        registry=registry,
        through=date(2026, 5, 1),
        name="golf_v1",
        trainer=GBDTTrainer(_SMALL_DATA_CONFIG),
        activate=False,
    )

    assert registry.get_active("golf_v1") is None


async def test_train_and_register_is_idempotent_for_same_inputs(tmp_path: Path) -> None:
    """Same data + config → same version id, so re-running never forks."""
    data = _separable_dataset()
    registry = ModelRegistry(tmp_path)

    v1 = await train_and_register(
        builder=_StubBuilder(data),  # type: ignore[arg-type]
        registry=registry,
        through=date(2026, 5, 1),
        name="golf_v1",
        trainer=GBDTTrainer(_SMALL_DATA_CONFIG),
    )
    v2 = await train_and_register(
        builder=_StubBuilder(data),  # type: ignore[arg-type]
        registry=registry,
        through=date(2026, 5, 1),
        name="golf_v1",
        trainer=GBDTTrainer(_SMALL_DATA_CONFIG),
    )

    assert v1.version_id == v2.version_id
    assert len(registry.list_versions("golf_v1")) == 1


# ---------------------------------------------------------------------------
# End-to-end against the real mock provider (slow)
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_end_to_end_trains_real_model_predictions_pick_it_up(
    tmp_path: Path,
) -> None:
    """The loop a fresh deploy runs: build from mock data, train, register,
    then confirm the predictions service serves the trained version rather
    than the ConstantModel fallback."""
    from app.ml.training import TrainingDataBuilder
    from app.providers.mock.mock_provider import MockDataProvider
    from app.services.catalog import CatalogService
    from app.services.features import FeatureExtractor
    from app.services.predictions import PredictionService

    provider = MockDataProvider(seed=42)
    catalog = CatalogService(provider)
    extractor = FeatureExtractor(provider)
    builder = TrainingDataBuilder(catalog=catalog, extractor=extractor)
    registry = ModelRegistry(tmp_path)

    version = await train_and_register(
        builder=builder,
        registry=registry,
        through=date(2022, 2, 15),
        name="golf_v1",
    )
    assert version.metrics["n_examples"] > 0

    active = registry.get_active("golf_v1")
    assert active is not None
    model = registry.load_artifact(active, model_cls=GBDTOutcomeModel)

    service = PredictionService(
        catalog=catalog,
        extractor=extractor,
        model=model,
        model_name="golf_v1",
        model_version_id=active.version_id,
    )
    # Score an upcoming tournament's field with the trained model.
    upcoming = await catalog.list_tournaments(limit=200)
    target = next(t for t in upcoming.items if t.start_date >= date(2022, 2, 15))
    result = await service.predict_tournament(
        target.id, as_of=date(2022, 2, 15)
    )
    assert result is not None
    assert result.model_version_id == active.version_id
    assert len(result.outcomes) > 0
    assert all(0.0 <= o.win_prob <= 1.0 for o in result.outcomes)
