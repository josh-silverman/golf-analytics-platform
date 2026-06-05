"""Model abstraction — doc 02 §6.

Every trained model implements ``predict(features) -> outcomes``. The
artifact is opaque to the registry; ``save``/``load`` default to pickle.
Concrete models (XGBoost, scikit-learn) override those two methods when
pickle isn't suitable.

We ship a ``ConstantModel`` so the registry → predictions plumbing can be
exercised end-to-end before any real training pipeline lands.
"""

from __future__ import annotations

import pickle  # noqa: S403 — only used for trusted, locally-trained artifacts
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


class Model(ABC):
    """A trained model that maps feature dicts to outcome dicts.

    The outcome dict's shape is contract between trainer and consumer —
    for the golf-prediction model it's keys like ``win_prob``, ``top_5_prob``,
    ``make_cut_prob``. ``predict`` doesn't enforce a schema so different
    model families can return different shapes.
    """

    @abstractmethod
    def predict(self, features: dict[str, float]) -> dict[str, float]:
        """Outcome probabilities for one player given their features."""

    def save(self, path: Path) -> None:
        """Default: pickle. Override for models with custom serialization."""
        path.write_bytes(pickle.dumps(self))

    @classmethod
    def load(cls, path: Path) -> Model:
        """Default: unpickle.

        Pickle is not safe against adversarial files — only load artifacts
        produced by this codebase. Real ops would gate this on a signed
        manifest or move to a safer format (ONNX, joblib).
        """
        obj = pickle.loads(path.read_bytes())  # noqa: S301 — see docstring
        if not isinstance(obj, cls):
            raise TypeError(
                f"Loaded artifact is {type(obj).__name__}, expected {cls.__name__}"
            )
        return obj


class ConstantModel(Model):
    """Predicts the same outcomes for every input.

    The placeholder model that lets the registry and ``/predictions``
    endpoint be exercised before real training lands. Also useful as a
    baseline in calibration diagnostics: "is the trained model actually
    better than predicting the field-average for every player?"
    """

    def __init__(self, outputs: dict[str, float]) -> None:
        # Defensive copy so callers can't mutate our state after construction.
        self._outputs = dict(outputs)

    def predict(self, features: dict[str, float]) -> dict[str, float]:
        # Return a copy so consumers can't mutate the stored output.
        return dict(self._outputs)
