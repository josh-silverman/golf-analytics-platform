"""The training CLI's activation guards.

Two separate guards live in ``_train``, both checked *before* training so a
refusal or a warning costs seconds, not an hour — these tests assert on that
by never letting a provider get built past the check point.

1. **Feature-set activation guard.** ``app.cli.train`` defaults to
   ``--feature-set v2`` while the registered active model is v3. Activating a
   v2 artifact repoints the serving extractor, because
   ``deps._feature_set_for_active_model`` resolves the feature set by the
   active model's hash, so the documented retrain command would quietly swap
   production's whole feature pipeline. This guard refuses that activation.

2. **Cold-start warning.** Path A's cold-start model is chosen by
   ``deps._latest_v2_cold_start`` as the newest ``training_data_through``
   among *registered* v2 versions, entirely independent of ``_active.txt``.
   So ``--no-activate`` does not mean "no production effect": a v2 trained
   "just to compare" can become what Path A serves on the next deploy without
   ever being activated. This is a warning, not a refusal — the run is
   allowed to proceed, but the terminal output must say so explicitly.
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


def _register_v2_candidate(root: Path, *, name: str, version_id: str, through: date) -> None:
    """Register a v2 version that is NOT active — a cold-start candidate only."""
    version_dir = root / name / version_id
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "metadata.json").write_text(
        json.dumps(
            {
                "name": name,
                "version_id": version_id,
                "feature_set_hash": v2_field_relative().hash,
                "training_data_through": through.isoformat(),
                "hyperparameters": {},
                "metrics": {},
                "trained_at": datetime(2026, 7, 3).isoformat(),
                "artifact_relpath": f"{name}/{version_id}/artifact.pkl",
            }
        )
    )


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


# ---------------------------------------------------------------------------
# Cold-start warning: --no-activate still changes what Path A serves
# ---------------------------------------------------------------------------


async def test_no_activate_v2_warns_when_no_v2_is_registered_yet(  # noqa: ANN201
    registry_root, monkeypatch, capsys
) -> None:
    """First-ever v2 registration: this run becomes the only cold-start candidate."""

    monkeypatch.setattr("app.providers.factory.get_data_provider", _raise_reached)
    with pytest.raises(ProviderReachedError):
        await _train(
            through=date(2026, 8, 1),
            name="golf_v1",
            season=None,
            activate=False,
            feature_set="v2",
        )
    out = capsys.readouterr().out
    assert "will NOT activate the stacked model" in out
    assert "WILL become the new Path A cold-start model" in out
    assert "No v2 model is currently registered" in out
    # The fixture's active model (v3) must not be misreported as affected.
    assert "0d2efade42ba" in out


async def test_no_activate_v2_warns_and_names_the_model_it_replaces(  # noqa: ANN201
    registry_root, monkeypatch, capsys
) -> None:
    """A newer through-date than the existing cold-start candidate: it flips."""

    _register_v2_candidate(
        registry_root, name="golf_v1", version_id="d69cf2a7323f", through=date(2026, 6, 30)
    )
    monkeypatch.setattr("app.providers.factory.get_data_provider", _raise_reached)
    with pytest.raises(ProviderReachedError):
        await _train(
            through=date(2026, 8, 24),  # newer than the registered candidate
            name="golf_v1",
            season=None,
            activate=False,
            feature_set="v2",
        )
    out = capsys.readouterr().out
    assert "WILL become the new Path A cold-start model" in out
    assert "Replaces the current cold-start model: d69cf2a7323f" in out
    assert "2026-06-30" in out


async def test_no_activate_v2_is_silent_when_it_would_not_win_cold_start(  # noqa: ANN201
    registry_root, monkeypatch, capsys
) -> None:
    """An older through-date than the existing candidate: cold-start is unaffected.

    This is the case a naive "did this run register a v2?" check would get
    wrong: registering is not the same as winning the newest-through-date
    selection, and a false alarm here is exactly the kind of warning that
    trains an operator to stop reading them.
    """

    _register_v2_candidate(
        registry_root, name="golf_v1", version_id="d69cf2a7323f", through=date(2026, 6, 30)
    )
    monkeypatch.setattr("app.providers.factory.get_data_provider", _raise_reached)
    with pytest.raises(ProviderReachedError):
        await _train(
            through=date(2026, 5, 1),  # older than the registered candidate
            name="golf_v1",
            season=None,
            activate=False,
            feature_set="v2",
        )
    out = capsys.readouterr().out
    assert "cold-start" not in out


async def test_no_activate_v2_is_silent_on_an_exact_tie(  # noqa: ANN201
    registry_root, monkeypatch, capsys
) -> None:
    """Equal through-dates: the incumbent wins the tie, mirroring _latest_v2_cold_start.

    ``deps._latest_v2_cold_start`` selects via ``max(..., key=through_date)``
    over versions ordered by ``trained_at``; Python's ``max`` keeps the FIRST
    value it sees at the maximum, so the older-registered version — earlier in
    that order — stays selected on a tie. The warning must match that exactly
    rather than firing on any registration with a through-date that merely
    reaches the incumbent.
    """

    _register_v2_candidate(
        registry_root, name="golf_v1", version_id="d69cf2a7323f", through=date(2026, 6, 30)
    )
    monkeypatch.setattr("app.providers.factory.get_data_provider", _raise_reached)
    with pytest.raises(ProviderReachedError):
        await _train(
            through=date(2026, 6, 30),  # ties the registered candidate
            name="golf_v1",
            season=None,
            activate=False,
            feature_set="v2",
        )
    out = capsys.readouterr().out
    assert "cold-start" not in out


async def test_no_activate_v3_never_warns_about_cold_start(  # noqa: ANN201
    registry_root, monkeypatch, capsys
) -> None:
    """v3 can never be selected as Path A cold-start, so it must never trigger this."""

    monkeypatch.setattr("app.providers.factory.get_data_provider", _raise_reached)
    with pytest.raises(ProviderReachedError):
        await _train(
            through=date(2026, 8, 24),
            name="golf_v1",
            season=None,
            activate=False,
            feature_set="v3",
        )
    out = capsys.readouterr().out
    assert "cold-start" not in out


async def test_activating_v2_does_not_use_the_no_activate_wording(  # noqa: ANN201
    tmp_path, monkeypatch, capsys
) -> None:
    """Activating is the normal path and must not print the --no-activate warning.

    Uses a fresh, empty registry so the feature-set guard (which only fires
    against a *different* active feature set) does not intervene.
    """

    class _Settings:
        model_registry_path = str(tmp_path / "empty")
        data_provider = "mock"

    monkeypatch.setattr("app.config.get_settings", lambda: _Settings())
    monkeypatch.setattr("app.providers.factory.get_data_provider", _raise_reached)
    with pytest.raises(ProviderReachedError):
        await _train(
            through=date(2026, 8, 24),
            name="golf_v1",
            season=None,
            activate=True,
            feature_set="v2",
        )
    out = capsys.readouterr().out
    assert "--no-activate will NOT activate" not in out
