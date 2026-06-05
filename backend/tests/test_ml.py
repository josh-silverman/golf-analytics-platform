"""Tests for the model abstraction and filesystem-backed registry."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest

from app.ml.base import ConstantModel, Model
from app.ml.registry import ModelRegistry, ModelVersion

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hp() -> dict[str, float | int | str]:
    return {"learning_rate": 0.1, "max_depth": 6, "objective": "binary:logistic"}


def _metrics() -> dict[str, float]:
    return {"auc": 0.78, "brier": 0.18, "log_loss": 0.51}


# ---------------------------------------------------------------------------
# ConstantModel
# ---------------------------------------------------------------------------


def test_constant_model_returns_configured_outputs() -> None:
    model = ConstantModel({"win_prob": 0.04, "top_10_prob": 0.25})
    assert model.predict({}) == {"win_prob": 0.04, "top_10_prob": 0.25}


def test_constant_model_predict_is_independent_copy() -> None:
    """Caller mutations to the returned dict must not affect later predicts."""
    model = ConstantModel({"win_prob": 0.04})
    first = model.predict({})
    first["win_prob"] = 999.0
    second = model.predict({})
    assert second == {"win_prob": 0.04}


def test_constant_model_ignores_input_features() -> None:
    model = ConstantModel({"win_prob": 0.10})
    assert model.predict({"sg_total_rating": 5.0}) == {"win_prob": 0.10}


# ---------------------------------------------------------------------------
# ModelVersion.compute_version_id
# ---------------------------------------------------------------------------


def test_version_id_is_deterministic_for_same_inputs() -> None:
    v1 = ModelVersion.compute_version_id("abc123", date(2026, 6, 1), _hp())
    v2 = ModelVersion.compute_version_id("abc123", date(2026, 6, 1), _hp())
    assert v1 == v2


def test_version_id_changes_when_feature_set_hash_changes() -> None:
    v1 = ModelVersion.compute_version_id("aaa", date(2026, 6, 1), _hp())
    v2 = ModelVersion.compute_version_id("bbb", date(2026, 6, 1), _hp())
    assert v1 != v2


def test_version_id_changes_when_hyperparameters_change() -> None:
    v1 = ModelVersion.compute_version_id("aaa", date(2026, 6, 1), {"lr": 0.1})
    v2 = ModelVersion.compute_version_id("aaa", date(2026, 6, 1), {"lr": 0.2})
    assert v1 != v2


def test_version_id_changes_when_training_through_date_changes() -> None:
    v1 = ModelVersion.compute_version_id("aaa", date(2026, 6, 1), _hp())
    v2 = ModelVersion.compute_version_id("aaa", date(2026, 6, 8), _hp())
    assert v1 != v2


def test_version_id_independent_of_hyperparameter_key_order() -> None:
    v1 = ModelVersion.compute_version_id(
        "aaa", date(2026, 6, 1), {"a": 1, "b": 2}
    )
    v2 = ModelVersion.compute_version_id(
        "aaa", date(2026, 6, 1), {"b": 2, "a": 1}
    )
    assert v1 == v2


def test_version_id_has_expected_length() -> None:
    vid = ModelVersion.compute_version_id("aaa", date(2026, 6, 1), _hp())
    assert len(vid) == 12


# ---------------------------------------------------------------------------
# ModelRegistry — register + get + list
# ---------------------------------------------------------------------------


def test_register_persists_metadata_and_artifact(tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path)
    version = registry.register(
        name="golf_v1",
        model=ConstantModel({"win_prob": 0.05}),
        feature_set_hash="abc123",
        training_data_through=date(2026, 6, 1),
        hyperparameters=_hp(),
        metrics=_metrics(),
    )
    version_dir = tmp_path / "golf_v1" / version.version_id
    assert (version_dir / "metadata.json").exists()
    assert (version_dir / "artifact.pkl").exists()


def test_register_idempotent_for_same_inputs(tmp_path: Path) -> None:
    """Two register() calls with identical inputs produce the same version_id."""
    registry = ModelRegistry(tmp_path)
    v1 = registry.register(
        name="golf",
        model=ConstantModel({"win_prob": 0.05}),
        feature_set_hash="abc",
        training_data_through=date(2026, 6, 1),
        hyperparameters=_hp(),
        metrics=_metrics(),
    )
    v2 = registry.register(
        name="golf",
        model=ConstantModel({"win_prob": 0.99}),  # different artifact
        feature_set_hash="abc",
        training_data_through=date(2026, 6, 1),
        hyperparameters=_hp(),
        metrics=_metrics(),
    )
    assert v1.version_id == v2.version_id


def test_get_round_trips_metadata(tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path)
    version = registry.register(
        name="golf",
        model=ConstantModel({"win_prob": 0.05}),
        feature_set_hash="abc",
        training_data_through=date(2026, 6, 1),
        hyperparameters=_hp(),
        metrics=_metrics(),
    )
    fetched = registry.get("golf", version.version_id)
    assert fetched.name == version.name
    assert fetched.version_id == version.version_id
    assert fetched.feature_set_hash == version.feature_set_hash
    assert fetched.training_data_through == version.training_data_through
    assert fetched.hyperparameters == version.hyperparameters
    assert fetched.metrics == version.metrics


def test_get_raises_for_unknown_version(tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path)
    with pytest.raises(KeyError, match="not found"):
        registry.get("ghost", "deadbeef0000")


def test_list_versions_empty_for_unknown_name(tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path)
    assert registry.list_versions("nope") == []


def test_list_versions_returns_all_registered(tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path)
    registry.register(
        name="golf",
        model=ConstantModel({"win_prob": 0.04}),
        feature_set_hash="aaa",
        training_data_through=date(2026, 6, 1),
        hyperparameters={"v": 1},
        metrics=_metrics(),
    )
    registry.register(
        name="golf",
        model=ConstantModel({"win_prob": 0.05}),
        feature_set_hash="bbb",
        training_data_through=date(2026, 6, 8),
        hyperparameters={"v": 2},
        metrics=_metrics(),
    )
    versions = registry.list_versions("golf")
    assert len(versions) == 2
    assert {v.feature_set_hash for v in versions} == {"aaa", "bbb"}


# ---------------------------------------------------------------------------
# ModelRegistry — active version
# ---------------------------------------------------------------------------


def test_get_active_returns_none_when_no_active(tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path)
    assert registry.get_active("golf") is None


def test_set_active_then_get_active(tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path)
    version = registry.register(
        name="golf",
        model=ConstantModel({"win_prob": 0.04}),
        feature_set_hash="aaa",
        training_data_through=date(2026, 6, 1),
        hyperparameters=_hp(),
        metrics=_metrics(),
    )
    registry.set_active("golf", version.version_id)
    active = registry.get_active("golf")
    assert active is not None
    assert active.version_id == version.version_id


def test_set_active_rejects_unknown_version(tmp_path: Path) -> None:
    registry = ModelRegistry(tmp_path)
    with pytest.raises(KeyError, match="not found"):
        registry.set_active("golf", "deadbeef0000")


# ---------------------------------------------------------------------------
# ModelRegistry — load_artifact (end-to-end)
# ---------------------------------------------------------------------------


def test_round_trip_register_load_predict(tmp_path: Path) -> None:
    """Register a model, reload it from disk, verify predictions match."""
    registry = ModelRegistry(tmp_path)
    original = ConstantModel({"win_prob": 0.07, "top_10_prob": 0.30})
    version = registry.register(
        name="golf",
        model=original,
        feature_set_hash="aaa",
        training_data_through=date(2026, 6, 1),
        hyperparameters=_hp(),
        metrics=_metrics(),
    )

    loaded = registry.load_artifact(version, model_cls=ConstantModel)
    assert isinstance(loaded, ConstantModel)
    assert loaded.predict({}) == {"win_prob": 0.07, "top_10_prob": 0.30}


def test_load_artifact_with_wrong_class_raises(tmp_path: Path) -> None:
    class _OtherModel(Model):
        def predict(self, features: dict[str, float]) -> dict[str, float]:
            return {}

    registry = ModelRegistry(tmp_path)
    version = registry.register(
        name="golf",
        model=ConstantModel({"win_prob": 0.04}),
        feature_set_hash="aaa",
        training_data_through=date(2026, 6, 1),
        hyperparameters=_hp(),
        metrics=_metrics(),
    )
    with pytest.raises(TypeError):
        registry.load_artifact(version, model_cls=_OtherModel)
