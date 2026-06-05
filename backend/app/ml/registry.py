"""Filesystem-backed model registry — doc 01 §4, doc 02 §6.

Each registered model lives at::

    {root}/{name}/{version_id}/
        metadata.json   (the ModelVersion)
        artifact.pkl    (the pickled Model)

with an ``_active.txt`` next to the version directories naming the
currently-active version for that model name.

``version_id`` is a 12-char SHA-256 prefix derived deterministically from
``(feature_set_hash, training_data_through, hyperparameters)``. Retraining
with the same inputs produces the same id — idempotent training, so
re-running a backfill never multiplies versions.

The DB-backed ``model_versions`` table from doc 02 §1 will eventually replace
the JSON metadata files; the abstraction stays the same so swapping the
backend is a constructor change.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from app.ml.base import Model


@dataclass(frozen=True)
class ModelVersion:
    """All the metadata recorded about a registered artifact.

    Fields mirror the columns described for the ``model_versions`` table
    (doc 02 §1) so the migration to a DB-backed registry is mechanical.
    """

    name: str
    version_id: str
    feature_set_hash: str
    training_data_through: date
    hyperparameters: dict[str, Any]
    metrics: dict[str, float]
    trained_at: datetime
    artifact_relpath: str

    @staticmethod
    def compute_version_id(
        feature_set_hash: str,
        training_data_through: date,
        hyperparameters: dict[str, Any],
    ) -> str:
        """Deterministic version id from the inputs that define a training run.

        ``hyperparameters`` must be JSON-serializable; non-serializable values
        raise at registration time, not at load time.
        """
        payload = json.dumps(
            {
                "feature_set_hash": feature_set_hash,
                "training_data_through": training_data_through.isoformat(),
                "hyperparameters": hyperparameters,
            },
            sort_keys=True,
        ).encode()
        return hashlib.sha256(payload).hexdigest()[:12]


class ModelRegistry:
    """Filesystem-backed registry. One instance per ``root`` directory."""

    _ACTIVE_FILE = "_active.txt"
    _METADATA_FILE = "metadata.json"
    _ARTIFACT_FILE = "artifact.pkl"

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    # --- Writes --------------------------------------------------------------

    def register(
        self,
        *,
        name: str,
        model: Model,
        feature_set_hash: str,
        training_data_through: date,
        hyperparameters: dict[str, Any],
        metrics: dict[str, float],
    ) -> ModelVersion:
        """Persist a model artifact and its metadata; return the version."""
        version_id = ModelVersion.compute_version_id(
            feature_set_hash, training_data_through, hyperparameters
        )
        version_dir = self._root / name / version_id
        version_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = version_dir / self._ARTIFACT_FILE
        model.save(artifact_path)

        version = ModelVersion(
            name=name,
            version_id=version_id,
            feature_set_hash=feature_set_hash,
            training_data_through=training_data_through,
            hyperparameters=hyperparameters,
            metrics=metrics,
            trained_at=datetime.now(UTC),
            artifact_relpath=str(artifact_path.relative_to(self._root)),
        )
        self._write_metadata(version)
        return version

    def set_active(self, name: str, version_id: str) -> None:
        """Mark ``version_id`` as the active version of ``name``.

        Raises ``KeyError`` if the version doesn't exist — no dangling
        pointers in the registry.
        """
        self.get(name, version_id)  # validates existence
        (self._root / name / self._ACTIVE_FILE).write_text(version_id)

    # --- Reads ---------------------------------------------------------------

    def get(self, name: str, version_id: str) -> ModelVersion:
        meta_path = self._root / name / version_id / self._METADATA_FILE
        if not meta_path.exists():
            raise KeyError(f"Model {name!r} version {version_id!r} not found")
        return self._read_metadata(meta_path)

    def list_versions(self, name: str) -> list[ModelVersion]:
        """All registered versions of ``name``, ordered by ``trained_at``."""
        name_dir = self._root / name
        if not name_dir.is_dir():
            return []
        versions: list[ModelVersion] = []
        for entry in name_dir.iterdir():
            if entry.is_dir() and (entry / self._METADATA_FILE).exists():
                versions.append(self._read_metadata(entry / self._METADATA_FILE))
        return sorted(versions, key=lambda v: v.trained_at)

    def get_active(self, name: str) -> ModelVersion | None:
        active_path = self._root / name / self._ACTIVE_FILE
        if not active_path.exists():
            return None
        version_id = active_path.read_text().strip()
        return self.get(name, version_id)

    def load_artifact(
        self,
        version: ModelVersion,
        *,
        model_cls: type[Model] | None = None,
    ) -> Model:
        """Load the pickled artifact for ``version``.

        If ``model_cls`` is provided, the loaded object is type-checked
        against it — useful when the caller knows the concrete class.
        """
        from app.ml.base import Model as _Model

        target = model_cls if model_cls is not None else _Model
        return target.load(self._root / version.artifact_relpath)

    # --- Internal ------------------------------------------------------------

    def _write_metadata(self, version: ModelVersion) -> None:
        meta_path = (
            self._root / version.name / version.version_id / self._METADATA_FILE
        )
        payload = {
            "name": version.name,
            "version_id": version.version_id,
            "feature_set_hash": version.feature_set_hash,
            "training_data_through": version.training_data_through.isoformat(),
            "hyperparameters": version.hyperparameters,
            "metrics": version.metrics,
            "trained_at": version.trained_at.isoformat(),
            "artifact_relpath": version.artifact_relpath,
        }
        meta_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    def _read_metadata(self, meta_path: Path) -> ModelVersion:
        data = json.loads(meta_path.read_text())
        return ModelVersion(
            name=data["name"],
            version_id=data["version_id"],
            feature_set_hash=data["feature_set_hash"],
            training_data_through=date.fromisoformat(data["training_data_through"]),
            hyperparameters=data["hyperparameters"],
            metrics=data["metrics"],
            trained_at=datetime.fromisoformat(data["trained_at"]),
            artifact_relpath=data["artifact_relpath"],
        )
