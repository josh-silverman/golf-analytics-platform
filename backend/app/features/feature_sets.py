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
    FieldRelativeSGApproach,
    FieldRelativeSGAroundTheGreen,
    FieldRelativeSGOffTheTee,
    FieldRelativeSGPutting,
    FieldRelativeSGTotal,
    FieldStrength,
    FormIndex,
    RoundCount,
    ScoreVolatility,
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


def v2_field_relative() -> FeatureSet:
    """Second composition — v1 skills plus field-relative context.

    Adds, on top of the v1 absolute ratings + form:
      * five ``field_rel_sg_*`` margins (player skill − field mean) so the
        model sees each player relative to the field they actually face;
      * ``field_strength`` (the field's mean SG-total) to scale confidence to
        the event's quality;
      * ``round_count`` so thin skill estimates can be discounted;
      * ``score_volatility`` (round-to-round SG-total spread) — the per-player
        variance the Monte Carlo simulation needs to model streaky vs. steady
        players, also exposed to the classifier.

    These are the levers that let the model separate winners from the pack —
    win/top-N probability is inherently a relative quantity. Requires
    field-aware extraction (``FeatureExtractor.extract_field``); single-player
    extraction leaves the field-relative features at a neutral 0.0.
    """
    return FeatureSet(
        name="v2_field_relative",
        features=[
            SGOffTheTeeRating(),
            SGApproachRating(),
            SGAroundTheGreenRating(),
            SGPuttingRating(),
            SGTotalRating(),
            FormIndex(),
            FieldRelativeSGOffTheTee(),
            FieldRelativeSGApproach(),
            FieldRelativeSGAroundTheGreen(),
            FieldRelativeSGPutting(),
            FieldRelativeSGTotal(),
            FieldStrength(),
            RoundCount(),
            ScoreVolatility(),
        ],
    )
