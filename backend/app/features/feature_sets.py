"""Named, versioned feature compositions.

Each function returns a fresh ``FeatureSet`` so the registry can be
constructed wherever it's needed (training, inference, tests) without
worrying about shared state. Adding a new set or bumping a version is the
single act that invalidates downstream predictions; the feature-set hash
captures it.
"""

from __future__ import annotations

from app.features.base import FeatureSet
from app.features.dg_preds import (
    DGMakeCutProb,
    DGTop10Prob,
    DGTop20Prob,
    HasDGPred,
)
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


def v3_dg_preds() -> FeatureSet:
    """v2 plus DataGolf's own pre-event model probabilities as meta-features.

    Extends ``v2_field_relative`` with four external-signal features
    (``dg_make_cut``, ``dg_top_20``, ``dg_top_10``, ``has_dg_pred``) sourced
    from DataGolf's Pre-Tournament Predictions Archive (``baseline_history_fit``
    column, ``fin_text`` never read). These target the make-cut/top-20 markets
    with genuine headroom and are orthogonal to the SG-rolling features — see
    ``app.features.dg_preds``. Requires field/event-aware extraction with an
    event supplied (``FeatureExtractor.extract_field(..., event=...)``); without
    it the DG features fall back to their cold-start NaN.
    """
    base = v2_field_relative()
    return FeatureSet(
        name="v3_dg_preds",
        features=[
            *base.features,
            DGMakeCutProb(),
            DGTop20Prob(),
            DGTop10Prob(),
            HasDGPred(),
        ],
    )
