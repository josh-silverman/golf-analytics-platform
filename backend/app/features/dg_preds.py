"""External-signal features: DataGolf pre-tournament model probabilities.

These are *meta-features* — DataGolf's own pre-event model output for the
markets with genuine headroom (make-cut, top-20, top-10), folded in as inputs
to our model. They encode course-fit, field composition, and DataGolf's talent
model, none of which the ``v2_field_relative`` SG-rolling features capture, so
they are orthogonal signal rather than a restatement of what we already
compute (validated in the API audit — see the archive-admissibility findings).

Provenance and leakage:
  * Source is DataGolf's Pre-Tournament Predictions Archive
    (``baseline_history_fit`` column only — the audit's pre-registered primary
    candidate), confirmed to be a genuine frozen pre-event snapshot, not a
    retrospective refit.
  * The ``fin_text`` (actual result) that DataGolf staples onto each archive
    record is NEVER read — the provider drops it before these features ever see
    a value. See ``DataGolfProvider.get_pretournament_preds``.

Cold-start (2018–2019 events with no archive, or a player missing from an
event's archive): the three probability features return ``nan`` — never 0.0. A
0% probability is a nonsensical outlier that would mislead tree splits; NaN is
routed natively by ``HistGradientBoostingClassifier`` to whichever child
minimises loss. ``has_dg_pred`` is the paired 1.0/0.0 indicator so the model
can also learn the missingness directly.
"""

from __future__ import annotations

from app.features.base import Feature, FeatureContext

_NAN = float("nan")


class _DGPredProbability(Feature):
    """A single DataGolf pre-event market probability, or NaN on cold-start."""

    # Marks features that require ``FeatureContext.dg_pred`` to be populated, so
    # the extractor only pays the fetch cost for feature sets that use them.
    needs_dg_preds = True

    _prob_key: str  # key into context.dg_pred: make_cut / top_20 / top_10

    def compute(self, context: FeatureContext, deps: dict[str, float]) -> float:
        if context.dg_pred is None:
            return _NAN
        # A present dict always carries all three markets; ``.get`` with a NaN
        # default keeps a partial payload from silently reading as 0.0.
        return float(context.dg_pred.get(self._prob_key, _NAN))


class DGMakeCutProb(_DGPredProbability):
    name = "dg_make_cut"
    version = 1
    _prob_key = "make_cut"


class DGTop20Prob(_DGPredProbability):
    name = "dg_top_20"
    version = 1
    _prob_key = "top_20"


class DGTop10Prob(_DGPredProbability):
    name = "dg_top_10"
    version = 1
    _prob_key = "top_10"


class HasDGPred(Feature):
    """1.0 when this (player, event) has a DataGolf pre-event prediction.

    Lets the model split on missingness explicitly, in addition to the NaN
    routing the three probability features rely on.
    """

    name = "has_dg_pred"
    version = 1
    needs_dg_preds = True

    def compute(self, context: FeatureContext, deps: dict[str, float]) -> float:
        return 1.0 if context.dg_pred is not None else 0.0
