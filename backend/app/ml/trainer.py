"""Model training — doc 01 §4 (Phase 2), doc 02 §6.

Fits a gradient-boosted model against a built ``TrainingData`` set and
hands the artifact to the ``ModelRegistry``. Phase 2's goal (doc 01 §4) is
"one trained model producing real predictions for a tournament", so this
trains one classifier per outcome (``win``, ``top_5`` ... ``made_cut``) and
exposes them behind a single ``Model``.

Model family. Decision 3 (doc 01 §3) calls for a gradient-boosted decision
tree behind a ``fit`` / ``predict_proba`` abstraction. We use scikit-learn's
``HistGradientBoostingClassifier`` rather than XGBoost: it is the same model
family but needs no OpenMP system library, so ``uv sync`` works unchanged on
a fresh laptop, in CI, and in the deploy image. Swapping in an
``XGBoostTrainer`` later is a new ``Trainer`` subclass — nothing downstream
of ``Model.predict`` changes.

Prediction targets. Decision 4 (doc 01 §3) ultimately prefers a skill →
simulation model (Approach C); that is the Phase 3 simulation engine. The
per-outcome classifiers here are the Phase 2 stepping stone that makes the
leaderboard real. When the Monte Carlo engine lands, it derives coherent
probabilities from a skill model and supersedes these marginals.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import brier_score_loss

from app.ml.base import Model
from app.ml.training import LABEL_KEYS

if TYPE_CHECKING:
    from datetime import date

    from numpy.typing import NDArray

    from app.ml.registry import ModelRegistry, ModelVersion
    from app.ml.training import TrainingData, TrainingDataBuilder


# Training labels (``win``, ``made_cut`` ...) are named for the outcome;
# the prediction layer (PredictionService) reads ``*_prob`` keys. This is
# the one place the two vocabularies meet.
LABEL_TO_OUTCOME_KEY: dict[str, str] = {
    "win": "win_prob",
    "top_5": "top_5_prob",
    "top_10": "top_10_prob",
    "top_20": "top_20_prob",
    "made_cut": "make_cut_prob",
}


def _positive_proba(estimator: Any, x: NDArray[np.float64]) -> float:
    """P(label == 1) for a single feature row.

    A degenerate outcome (every training example shared one label — e.g.
    ``win`` is almost always 0) leaves the classifier with a single class.
    sklearn still fits, but ``predict_proba`` returns one column, so read
    the constant directly instead of indexing a missing positive column.
    """
    classes = [int(c) for c in estimator.classes_]
    if len(classes) == 1:
        return 1.0 if classes[0] == 1 else 0.0
    proba = estimator.predict_proba(x)[0]
    return float(proba[classes.index(1)])


class GBDTOutcomeModel(Model):
    """One gradient-boosted classifier per outcome, behind a single Model.

    ``feature_names`` fixes the vector layout at fit time so training and
    inference build the identical row from a feature dict — the
    training/serving-skew guard from Decision 6. Features absent from an
    input dict default to 0.0; extra keys are ignored.
    """

    def __init__(
        self,
        *,
        feature_names: tuple[str, ...],
        estimators: dict[str, Any],
    ) -> None:
        self._feature_names = feature_names
        self._estimators = estimators

    def _vectorize(self, features: dict[str, float]) -> NDArray[np.float64]:
        return np.array(
            [[float(features.get(name, 0.0)) for name in self._feature_names]],
            dtype=np.float64,
        )

    def predict(self, features: dict[str, float]) -> dict[str, float]:
        x = self._vectorize(features)
        return {
            outcome_key: _positive_proba(estimator, x)
            for outcome_key, estimator in self._estimators.items()
        }


@dataclass(frozen=True)
class TrainerConfig:
    """Hyperparameters for the GBDT trainer.

    Serialized verbatim into the model version's id (so a config change
    yields a new version) and stored as registry metadata. ``model_family``
    is recorded so a future XGBoost trainer never collides with these ids.
    """

    max_iter: int = 200
    max_depth: int | None = 3
    learning_rate: float = 0.05
    min_samples_leaf: int = 20
    l2_regularization: float = 0.0
    random_state: int = 0

    def as_hyperparameters(self) -> dict[str, Any]:
        return {
            "model_family": "sklearn.HistGradientBoostingClassifier",
            "max_iter": self.max_iter,
            "max_depth": self.max_depth,
            "learning_rate": self.learning_rate,
            "min_samples_leaf": self.min_samples_leaf,
            "l2_regularization": self.l2_regularization,
            "random_state": self.random_state,
        }


@dataclass(frozen=True)
class TrainingResult:
    """A fitted model plus everything the registry needs to record it."""

    model: GBDTOutcomeModel
    feature_names: tuple[str, ...]
    metrics: dict[str, float]
    hyperparameters: dict[str, Any]


def _collect_feature_names(data: TrainingData) -> tuple[str, ...]:
    """Sorted union of every feature key seen across examples.

    Sorted for determinism: the same dataset always yields the same vector
    layout, so the model id is reproducible.
    """
    names: set[str] = set()
    for example in data.examples:
        names.update(example.features)
    return tuple(sorted(names))


def _in_sample_brier(
    estimator: Any, x: NDArray[np.float64], y: NDArray[np.int_]
) -> float:
    """Brier score of the classifier on the data it was fit on.

    In-sample and therefore optimistic — it is a sanity signal, not a
    generalization estimate. Held-out calibration (isotonic regression,
    reliability diagrams) is the Phase 2 follow-on that measures this
    honestly.
    """
    classes = [int(c) for c in estimator.classes_]
    if len(classes) == 1:
        const = 1.0 if classes[0] == 1 else 0.0
        return float(np.mean((const - y) ** 2))
    proba = estimator.predict_proba(x)[:, classes.index(1)]
    return float(brier_score_loss(y, proba))


class Trainer(ABC):
    """Fits a ``TrainingData`` set into a ``Model`` plus training metadata."""

    @property
    @abstractmethod
    def hyperparameters(self) -> dict[str, Any]:
        """JSON-serializable config — feeds the deterministic version id."""

    @abstractmethod
    def fit(self, data: TrainingData) -> TrainingResult:
        """Train one model over the dataset and report its metrics."""


class GBDTTrainer(Trainer):
    """Gradient-boosted trainer: one classifier per outcome key."""

    def __init__(self, config: TrainerConfig | None = None) -> None:
        self._config = config or TrainerConfig()

    @property
    def hyperparameters(self) -> dict[str, Any]:
        return self._config.as_hyperparameters()

    def fit(self, data: TrainingData) -> TrainingResult:
        if len(data) == 0:
            raise ValueError("Cannot train on an empty dataset")

        feature_names = _collect_feature_names(data)
        x = np.array(
            [
                [float(ex.features.get(name, 0.0)) for name in feature_names]
                for ex in data.examples
            ],
            dtype=np.float64,
        )

        estimators: dict[str, Any] = {}
        metrics: dict[str, float] = {}
        for label_key in LABEL_KEYS:
            outcome_key = LABEL_TO_OUTCOME_KEY[label_key]
            y: NDArray[np.int_] = np.array(
                [ex.labels[label_key] for ex in data.examples], dtype=np.int_
            )
            estimator = HistGradientBoostingClassifier(
                max_iter=self._config.max_iter,
                max_depth=self._config.max_depth,
                learning_rate=self._config.learning_rate,
                min_samples_leaf=self._config.min_samples_leaf,
                l2_regularization=self._config.l2_regularization,
                random_state=self._config.random_state,
            )
            estimator.fit(x, y)
            estimators[outcome_key] = estimator
            metrics[f"brier_{outcome_key}"] = _in_sample_brier(estimator, x, y)

        metrics["n_examples"] = float(len(data))
        metrics["n_features"] = float(len(feature_names))

        model = GBDTOutcomeModel(feature_names=feature_names, estimators=estimators)
        return TrainingResult(
            model=model,
            feature_names=feature_names,
            metrics=metrics,
            hyperparameters=self.hyperparameters,
        )


async def train_and_register(
    *,
    builder: TrainingDataBuilder,
    registry: ModelRegistry,
    through: date,
    name: str,
    trainer: Trainer | None = None,
    season: int | None = None,
    activate: bool = True,
) -> ModelVersion:
    """Close the loop: build a dataset, fit a model, register it.

    Returns the registered ``ModelVersion``. With ``activate`` (the default)
    the new version becomes the active model, so ``/predictions`` serves it
    on the next request instead of the ConstantModel fallback.
    """
    trainer = trainer or GBDTTrainer()
    data = await builder.build(through=through, season=season)
    result = trainer.fit(data)
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
