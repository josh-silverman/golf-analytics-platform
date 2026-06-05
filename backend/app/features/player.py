"""Player-centric features: time-decayed SG skill ratings + form index.

These are the v1 "skill estimate" features that go into the first model.
Field-strength adjustment (doc 02 §3) is deliberately deferred — it lands
once the ingestion pipeline populates ``field_strength`` on tournaments.
"""

from __future__ import annotations

from app.features.base import Feature, FeatureContext
from app.features.primitives import (
    days_between,
    exponential_decay_weight,
    weighted_mean,
)

# Half-life for time decay. 60 days sits in the middle of the doc 02 §3
# recommended range (60–90 days). Lower would over-react to single hot weeks;
# higher would underweight current form.
_DECAY_HALF_LIFE_DAYS = 60.0


class _SGSkillRating(Feature):
    """Common implementation for the SG-category skill ratings.

    Computed as a time-decayed weighted average of the player's per-round
    SG values in one category.
    """

    _attribute: str  # column on Round: sg_ott / sg_app / sg_arg / sg_putt / sg_total

    def compute(
        self,
        context: FeatureContext,
        deps: dict[str, float],
    ) -> float:
        if not context.rounds:
            return 0.0
        values: list[float] = []
        weights: list[float] = []
        for dated in context.rounds:
            days_ago = days_between(dated.played_on, context.as_of_date)
            weights.append(exponential_decay_weight(days_ago, _DECAY_HALF_LIFE_DAYS))
            values.append(getattr(dated.round, self._attribute))
        return weighted_mean(values, weights)


class SGOffTheTeeRating(_SGSkillRating):
    name = "sg_ott_rating"
    version = 1
    _attribute = "sg_ott"


class SGApproachRating(_SGSkillRating):
    name = "sg_app_rating"
    version = 1
    _attribute = "sg_app"


class SGAroundTheGreenRating(_SGSkillRating):
    name = "sg_arg_rating"
    version = 1
    _attribute = "sg_arg"


class SGPuttingRating(_SGSkillRating):
    name = "sg_putt_rating"
    version = 1
    _attribute = "sg_putt"


class SGTotalRating(_SGSkillRating):
    name = "sg_total_rating"
    version = 1
    _attribute = "sg_total"


class FormIndex(Feature):
    """Recent SG total minus long-run SG total — positive means heating up.

    Per doc 02 §3:
        rolling_mean(sg_total, last_8_rounds)
        - long_run_mean(sg_total, last_50_rounds)

    One number that captures "is this player playing above their baseline
    right now?" — useful as a domain-aware signal beyond the skill ratings.
    """

    name = "form_index"
    version = 1
    depends_on = ()

    _RECENT_WINDOW = 8
    _BASELINE_WINDOW = 50

    def compute(
        self,
        context: FeatureContext,
        deps: dict[str, float],
    ) -> float:
        if not context.rounds:
            return 0.0
        ordered = sorted(context.rounds, key=lambda r: r.played_on, reverse=True)
        recent = ordered[: self._RECENT_WINDOW]
        baseline = ordered[: self._BASELINE_WINDOW]
        recent_mean = sum(r.round.sg_total for r in recent) / len(recent)
        baseline_mean = sum(r.round.sg_total for r in baseline) / len(baseline)
        return recent_mean - baseline_mean
