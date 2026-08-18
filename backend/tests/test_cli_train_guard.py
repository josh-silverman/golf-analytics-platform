"""The training CLI's feature-set activation guard.

``app.cli.train`` defaults to ``--feature-set v2`` while the registered active
model is v3. Activating a v2 artifact repoints the serving extractor, because
``deps._feature_set_for_active_model`` resolves the feature set by the active
model's hash, so the documented retrain command would quietly swap production's
whole feature pipeline. The guard refuses that activation.

It is checked *before* training so the refusal costs seconds, not an hour: these
tests assert the exit happens without a provider ever being built.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path  # noqa: TC003 — runtime annotation on a module-level helper

import pytest

from app.cli.train import _train
from app.features.feature_sets import v2_field_relative, v3_dg_preds


class ProviderReachedError(RuntimeError):
    """Raised by the provider stub — reaching it proves the guard let the run through."""


def _raise_reached():  # noqa: ANN202
    raise ProviderReachedError


def _register_active(root: Path, *, name: str, version_id: str, feature_set_hash: str) -> None:
    """Write the metadata + active pointer the registry reads, without an artifact.

    ``get_active`` only reads these two files; the pickle is loaded lazily and
    the guard never gets that far.
    """
    version_dir = root / name / version_id
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "metadata.json").write_text(
        json.dumps(
            {
                "name": name,
                "version_id": version_id,
                "feature_set_hash": feature_set_hash,
                "training_data_through": date(2026, 6, 30).isoformat(),
                "hyperparameters": {},
                "metrics": {},
                "trained_at": datetime(2026, 7, 2).isoformat(),
                "artifact_relpath": f"{name}/{version_id}/artifact.pkl",
            }
        )
    )
    (root / name / "_active.txt").write_text(version_id)


@pytest.fixture
def registry_root(tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    """A registry whose active model is v3, with settings pointed at it."""
    root = tmp_path / "models"
    _register_active(
        root, name="golf_v1", version_id="0d2efade42ba", feature_set_hash=v3_dg_preds().hash
    )

    class _Settings:
        model_registry_path = str(root)
        data_provider = "mock"

    monkeypatch.setattr("app.config.get_settings", lambda: _Settings())
    # Any attempt to build a provider means the guard did not fire first.
    monkeypatch.setattr(
        "app.providers.factory.get_data_provider",
        lambda: pytest.fail("guard should have exited before building a provider"),
    )
    return root


async def test_activating_a_different_feature_set_is_refused(registry_root) -> None:  # noqa: ANN001
    """The documented retrain command against a v3 production model must not run."""
    with pytest.raises(SystemExit) as exc:
        await _train(
            through=date(2026, 8, 1),
            name="golf_v1",
            season=None,
            activate=True,
            feature_set="v2",  # the CLI default
        )
    assert exc.value.code == 2


async def test_refusal_names_both_feature_sets(registry_root, capsys) -> None:  # noqa: ANN001
    """The operator needs to see what is active and what was about to replace it."""
    with pytest.raises(SystemExit):
        await _train(
            through=date(2026, 8, 1),
            name="golf_v1",
            season=None,
            activate=True,
            feature_set="v2",
        )
    err = capsys.readouterr().err
    assert "0d2efade42ba" in err
    assert v3_dg_preds().hash[:12] in err
    assert v2_field_relative().hash[:12] in err
    assert "--no-activate" in err


async def test_no_activate_skips_the_guard(registry_root, monkeypatch) -> None:  # noqa: ANN001
    """Registering without activating is safe, so it must not be blocked.

    Reaching the provider is the success signal here: it proves the guard let
    the run through. The stub raises so the test stops before real training.
    """

    monkeypatch.setattr("app.providers.factory.get_data_provider", _raise_reached)
    with pytest.raises(ProviderReachedError):
        await _train(
            through=date(2026, 8, 1),
            name="golf_v1",
            season=None,
            activate=False,
            feature_set="v2",
        )


async def test_explicit_override_is_honoured(registry_root, monkeypatch) -> None:  # noqa: ANN001
    """A deliberate feature-set swap is allowed once it is stated explicitly."""

    monkeypatch.setattr("app.providers.factory.get_data_provider", _raise_reached)
    with pytest.raises(ProviderReachedError):
        await _train(
            through=date(2026, 8, 1),
            name="golf_v1",
            season=None,
            activate=True,
            feature_set="v2",
            allow_feature_set_change=True,
        )


async def test_matching_feature_set_activates_normally(registry_root, monkeypatch) -> None:  # noqa: ANN001
    """Retraining the *same* feature set is the normal path and stays unblocked."""

    monkeypatch.setattr("app.providers.factory.get_data_provider", _raise_reached)
    with pytest.raises(ProviderReachedError):
        await _train(
            through=date(2026, 8, 1),
            name="golf_v1",
            season=None,
            activate=True,
            feature_set="v3",  # matches the active model
        )


async def test_guard_is_inert_on_a_fresh_registry(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    """With nothing active yet there is nothing to protect, so training proceeds."""

    class _Settings:
        model_registry_path = str(tmp_path / "empty")
        data_provider = "mock"

    monkeypatch.setattr("app.config.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.providers.factory.get_data_provider", _raise_reached)
    with pytest.raises(ProviderReachedError):
        await _train(
            through=date(2026, 8, 1),
            name="golf_v1",
            season=None,
            activate=True,
            feature_set="v2",
        )
