"""Named, versioned feature compositions.

Each function returns a fresh ``FeatureSet`` so the registry can be
constructed wherever it's needed (training, inference, tests) without
worrying about shared state. Adding a new set or bumping a version is the
single act that invalidates downstream predictions; the feature-set hash
captures it.
"""

from __future__ import annotations

from app.features.base import FeatureSet
from app.features.player import (
    FormIndex,
    SGApproachRating,
    SGAroundTheGreenRating,
    SGOffTheTeeRating,
    SGPuttingRating,
    SGTotalRating,
)


def v1_baseline() -> FeatureSet:
    """First feature composition — four SG categories + total + form.

    The hash is determined by the sorted (name, version) tuples of these
    features. Bump any feature's ``version`` to invalidate predictions that
    were generated against the old definition.
    """
    return FeatureSet(
        name="v1_baseline",
        features=[
            SGOffTheTeeRating(),
            SGApproachRating(),
            SGAroundTheGreenRating(),
            SGPuttingRating(),
            SGTotalRating(),
            FormIndex(),
        ],
    )
