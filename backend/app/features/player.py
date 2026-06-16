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
)

# Half-life for time decay. 60 days sits in the middle of the doc 02 §3
# recommended range (60–90 days). Lower would over-react to single hot weeks;
# higher would underweight current form.
_DECAY_HALF_LIFE_DAYS = 60.0

# Low-data shrinkage. A player we have little history on is treated as a
# *below-average* tour player, not an average one: the rating is a weighted
# blend of the player's (time-decayed) observed SG and a negative prior worth
# ``_PRIOR_PSEUDO_WEIGHT`` rounds. A rich history overwhelms the prior; a thin
# one (a Monday qualifier, a journeyman with two fetched rounds) stays anchored
# below the field, instead of defaulting to the field mean and producing the
# phantom betting edges a flat 0.0 caused. Leakage-safe — a fixed prior plus the
# player's own past rounds — and identical in training and serving. Magnitudes
# are tuned against the rolling backtest, not guessed at runtime.
_PRIOR_PSEUDO_WEIGHT = 5.0


def shrink_to_prior(weighted_total: float, weight_sum: float, prior: float) -> float:
    """Blend an observed weighted sum with a prior worth ``_PRIOR_PSEUDO_WEIGHT``.

    ``weighted_total`` is Σ(wᵢ·valueᵢ) and ``weight_sum`` is Σwᵢ; with no
    observations (``weight_sum == 0``) the result is exactly ``prior``.
    """
    return (weighted_total + _PRIOR_PSEUDO_WEIGHT * prior) / (
        weight_sum + _PRIOR_PSEUDO_WEIGHT
    )


class _SGSkillRating(Feature):
    """Common implementation for the SG-category skill ratings.

    A time-decayed weighted average of the player's per-round SG in one
    category, shrunk toward a below-average prior so thin histories don't read
    as "average" (see ``shrink_to_prior``).
    """

    _attribute: str  # column on Round: sg_ott / sg_app / sg_arg / sg_putt / sg_total
    _prior: float    # below-average SG this category regresses to with no data

    def compute(
        self,
        context: FeatureContext,
        deps: dict[str, float],
    ) -> float:
        weighted_total = 0.0
        weight_sum = 0.0
        for dated in context.rounds:
            days_ago = days_between(dated.played_on, context.as_of_date)
            w = exponential_decay_weight(days_ago, _DECAY_HALF_LIFE_DAYS)
            weight_sum += w
            weighted_total += w * getattr(dated.round, self._attribute)
        return shrink_to_prior(weighted_total, weight_sum, self._prior)


class SGOffTheTeeRating(_SGSkillRating):
    name = "sg_ott_rating"
    version = 2
    _attribute = "sg_ott"
    _prior = -0.10


class SGApproachRating(_SGSkillRating):
    name = "sg_app_rating"
    version = 2
    _attribute = "sg_app"
    _prior = -0.20


class SGAroundTheGreenRating(_SGSkillRating):
    name = "sg_arg_rating"
    version = 2
    _attribute = "sg_arg"
    _prior = -0.05


class SGPuttingRating(_SGSkillRating):
    name = "sg_putt_rating"
    version = 2
    _attribute = "sg_putt"
    _prior = -0.15


class SGTotalRating(_SGSkillRating):
    name = "sg_total_rating"
    version = 2
    _attribute = "sg_total"
    _prior = -0.50


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


# ---------------------------------------------------------------------------
# Field-relative features (v2) — a player's edge over the field they face.
#
# Win and top-N probabilities are inherently relative: a +1.0 SG player is a
# heavy favourite in a weak field and a coin-flip in a major. The v1 features
# describe a player in isolation, which is why the model couldn't separate
# winners from the pack. These read the field aggregates the extractor attaches
# and express each skill *as a margin over the field mean*, plus the field's
# absolute strength so the model can scale its confidence to the event.
# ---------------------------------------------------------------------------


class _FieldRelativeSG(Feature):
    """A player's SG-category skill minus the field's mean in that category.

    Depends on the corresponding absolute rating so the registry computes the
    player's own value first; the field mean comes from ``context.field``.
    Falls back to 0.0 (player at the field average) when there's no field —
    e.g. single-player extraction on the player-detail page.
    """

    _source: str  # name of the absolute rating feature to subtract the field mean of

    def compute(
        self,
        context: FeatureContext,
        deps: dict[str, float],
    ) -> float:
        own = deps[self._source]
        if context.field is None:
            return 0.0
        field_mean = context.field.mean_skill.get(self._source, own)
        return own - field_mean


class FieldRelativeSGTotal(_FieldRelativeSG):
    name = "field_rel_sg_total"
    version = 1
    _source = "sg_total_rating"
    depends_on = ("sg_total_rating",)


class FieldRelativeSGOffTheTee(_FieldRelativeSG):
    name = "field_rel_sg_ott"
    version = 1
    _source = "sg_ott_rating"
    depends_on = ("sg_ott_rating",)


class FieldRelativeSGApproach(_FieldRelativeSG):
    name = "field_rel_sg_app"
    version = 1
    _source = "sg_app_rating"
    depends_on = ("sg_app_rating",)


class FieldRelativeSGAroundTheGreen(_FieldRelativeSG):
    name = "field_rel_sg_arg"
    version = 1
    _source = "sg_arg_rating"
    depends_on = ("sg_arg_rating",)


class FieldRelativeSGPutting(_FieldRelativeSG):
    name = "field_rel_sg_putt"
    version = 1
    _source = "sg_putt_rating"
    depends_on = ("sg_putt_rating",)


class FieldStrength(Feature):
    """The field's mean SG-total skill — how strong is the event overall?

    Identical for every player in a given event; lets the model scale a
    player's edge by the quality of the opposition (a 1-stroke edge means
    more in a strong field). Neutral 0.0 without a field context.
    """

    name = "field_strength"
    version = 1
    depends_on = ("sg_total_rating",)

    def compute(
        self,
        context: FeatureContext,
        deps: dict[str, float],
    ) -> float:
        if context.field is None:
            return 0.0
        return context.field.mean_skill.get("sg_total_rating", 0.0)


class RoundCount(Feature):
    """Number of rounds the skill estimate is built from — a confidence proxy.

    A +1.0 SG average over 60 rounds is a far surer thing than the same number
    over 4. Giving the model the sample size lets it discount thin histories
    instead of treating every estimate as equally certain.
    """

    name = "round_count"
    version = 1
    depends_on = ()

    def compute(
        self,
        context: FeatureContext,
        deps: dict[str, float],
    ) -> float:
        return float(len(context.rounds))


class ScoreVolatility(Feature):
    """Round-to-round scoring volatility — the player's own variance estimate.

    Standard deviation of the player's recent per-round SG-total. Because
    SG-total is a field-relative round score, its spread is exactly the
    round-score variance the Monte Carlo engine needs: a streaky player (high
    volatility) both wins and misses cuts more often than a metronome at the
    same skill mean. The simulation reads this as each player's ``score_std``.

    Returns 0.0 when there are too few rounds to estimate a stable spread; the
    engine reads 0.0 as "unknown" and falls back to the field-default σ, so a
    thin history never produces a degenerate (near-zero variance) simulation.
    """

    name = "score_volatility"
    version = 1
    depends_on = ()

    _MIN_ROUNDS = 5
    _WINDOW = 20

    def compute(
        self,
        context: FeatureContext,
        deps: dict[str, float],
    ) -> float:
        if len(context.rounds) < self._MIN_ROUNDS:
            return 0.0
        ordered = sorted(context.rounds, key=lambda r: r.played_on, reverse=True)
        values = [r.round.sg_total for r in ordered[: self._WINDOW]]
        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        return float(variance**0.5)
