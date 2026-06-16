"""Unit tests for the feature engineering foundation.

Covers:
1. The decay/weighted-mean primitives — closed-form checks.
2. ``FeatureRegistry`` topological order + cycle detection.
3. ``FeatureSet`` hash determinism.
4. The SG-rating and form-index features against hand-computed expected
   values on tiny fixtures.
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from app.domain.models import Round
from app.features.base import (
    DatedRound,
    Feature,
    FeatureContext,
    FeatureRegistry,
    FeatureSet,
    FieldContext,
)
from app.features.feature_sets import v1_baseline, v2_field_relative
from app.features.player import (
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
    shrink_to_prior,
)
from app.features.primitives import (
    days_between,
    exponential_decay_weight,
    weighted_mean,
)

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _make_round(
    *,
    rid: int,
    sg_ott: float = 0.0,
    sg_app: float = 0.0,
    sg_arg: float = 0.0,
    sg_putt: float = 0.0,
    sg_total: float | None = None,
) -> Round:
    """Build a minimal valid Round. SG_total defaults to the sum of parts."""
    total = sg_total if sg_total is not None else sg_ott + sg_app + sg_arg + sg_putt
    return Round(
        id=rid,
        entry_id=rid,
        round_number=1,
        score=70,
        score_to_par=-2,
        sg_ott=sg_ott,
        sg_app=sg_app,
        sg_arg=sg_arg,
        sg_putt=sg_putt,
        sg_t2g=sg_ott + sg_app + sg_arg,
        sg_total=total,
    )


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def test_exponential_decay_at_zero_is_one() -> None:
    assert exponential_decay_weight(0, 60.0) == pytest.approx(1.0)


def test_exponential_decay_at_half_life_is_one_half() -> None:
    assert exponential_decay_weight(60, 60.0) == pytest.approx(0.5)


def test_exponential_decay_at_two_half_lives_is_one_quarter() -> None:
    assert exponential_decay_weight(120, 60.0) == pytest.approx(0.25)


def test_exponential_decay_clamps_negative_to_one() -> None:
    assert exponential_decay_weight(-10, 60.0) == pytest.approx(1.0)


def test_exponential_decay_rejects_non_positive_half_life() -> None:
    with pytest.raises(ValueError, match="half_life_days"):
        exponential_decay_weight(30, 0.0)


def test_weighted_mean_basic() -> None:
    assert weighted_mean([1.0, 2.0, 3.0], [1.0, 1.0, 1.0]) == pytest.approx(2.0)


def test_weighted_mean_unequal_weights() -> None:
    # (1*1 + 2*3) / (1 + 3) = 7/4 = 1.75
    assert weighted_mean([1.0, 2.0], [1.0, 3.0]) == pytest.approx(1.75)


def test_weighted_mean_zero_total_weight_returns_zero() -> None:
    assert weighted_mean([1.0, 2.0], [0.0, 0.0]) == 0.0


def test_days_between() -> None:
    assert days_between(date(2026, 6, 1), date(2026, 6, 4)) == 3
    assert days_between(date(2026, 6, 4), date(2026, 6, 1)) == -3


# ---------------------------------------------------------------------------
# FeatureRegistry
# ---------------------------------------------------------------------------


class _ConstFeature(Feature):
    """Tiny test feature: returns a fixed value, declares no dependencies."""

    def __init__(self, name: str, value: float, deps: tuple[str, ...] = ()) -> None:
        self.name = name
        self.version = 1
        self.depends_on = deps
        self._value = value

    def compute(
        self,
        context: FeatureContext,
        deps: dict[str, float],
    ) -> float:
        # Pull from deps so the cycle/order tests actually exercise the graph.
        return self._value + sum(deps.values())


def _empty_context() -> FeatureContext:
    return FeatureContext(player_id=1, as_of_date=date(2026, 6, 4), rounds=())


def test_registry_topological_order_respects_deps() -> None:
    registry = FeatureRegistry([
        _ConstFeature("c", 3.0, deps=("a", "b")),
        _ConstFeature("a", 1.0),
        _ConstFeature("b", 2.0, deps=("a",)),
    ])
    # a must come before b; b before c.
    order = registry.order
    assert order.index("a") < order.index("b") < order.index("c")


def test_registry_computes_in_dependency_order() -> None:
    registry = FeatureRegistry([
        _ConstFeature("a", 1.0),
        _ConstFeature("b", 2.0, deps=("a",)),
        _ConstFeature("c", 3.0, deps=("a", "b")),
    ])
    values = registry.compute(_empty_context())
    assert values["a"] == 1.0
    assert values["b"] == 3.0  # 2 + a(1)
    assert values["c"] == 7.0  # 3 + a(1) + b(3)


def test_registry_rejects_missing_dependency() -> None:
    with pytest.raises(ValueError, match="not registered"):
        FeatureRegistry([_ConstFeature("a", 1.0, deps=("does_not_exist",))])


def test_registry_detects_cycle() -> None:
    with pytest.raises(ValueError, match="[Cc]yclic"):
        FeatureRegistry([
            _ConstFeature("a", 1.0, deps=("b",)),
            _ConstFeature("b", 2.0, deps=("a",)),
        ])


# ---------------------------------------------------------------------------
# FeatureSet hash
# ---------------------------------------------------------------------------


def test_feature_set_hash_is_deterministic_across_orderings() -> None:
    a = _ConstFeature("a", 1.0)
    b = _ConstFeature("b", 2.0)
    set_one = FeatureSet("v1", [a, b])
    set_two = FeatureSet("v1", [b, a])
    assert set_one.hash == set_two.hash


def test_feature_set_hash_changes_when_version_bumps() -> None:
    base = FeatureSet("v1", [SGOffTheTeeRating()])
    bumped_feature = SGOffTheTeeRating()
    bumped_feature.version = SGOffTheTeeRating().version + 1
    bumped = FeatureSet("v1", [bumped_feature])
    assert base.hash != bumped.hash


# ---------------------------------------------------------------------------
# Player features
# ---------------------------------------------------------------------------


def test_sg_rating_empty_rounds_returns_prior() -> None:
    """No history → the rating is exactly the below-average prior, not 0.0.

    This is the low-data fix: an unknown player reads as below the field, so the
    model doesn't hand thin-history longshots an average skill estimate.
    """
    feature = SGOffTheTeeRating()
    ctx = FeatureContext(player_id=1, as_of_date=date(2026, 6, 4), rounds=())
    assert feature.compute(ctx, {}) == pytest.approx(feature._prior)


def test_sg_rating_uniform_rounds_shrinks_toward_prior() -> None:
    """Three identical rounds (sg_ott=1.2) on the same day → weighted_total 3.6
    over weight_sum 3, blended with the prior's pseudo-weight."""
    rounds = tuple(
        DatedRound(_make_round(rid=i, sg_ott=1.2), date(2026, 6, 1))
        for i in range(3)
    )
    ctx = FeatureContext(player_id=1, as_of_date=date(2026, 6, 4), rounds=rounds)
    # Rounds are 3 days before as_of, so each carries the same decay weight.
    w = exponential_decay_weight(days_between(date(2026, 6, 1), date(2026, 6, 4)), 60.0)
    expected = shrink_to_prior(3 * 1.2 * w, 3 * w, SGOffTheTeeRating._prior)
    assert SGOffTheTeeRating().compute(ctx, {}) == pytest.approx(expected)
    # A rich, strong history still lands well above the prior.
    assert SGOffTheTeeRating().compute(ctx, {}) > SGOffTheTeeRating._prior


def test_sg_rating_weights_recent_round_more_than_old_round() -> None:
    """One round today (sg_ott=2, weight 1.0), one 60 days ago (sg_ott=0,
    weight 0.5): weighted_total 2.0 over weight_sum 1.5, then shrunk."""
    today = date(2026, 6, 4)
    rounds = (
        DatedRound(_make_round(rid=1, sg_ott=2.0), today),
        DatedRound(_make_round(rid=2, sg_ott=0.0), date(2026, 4, 5)),  # 60 days ago
    )
    ctx = FeatureContext(player_id=1, as_of_date=today, rounds=rounds)
    expected = shrink_to_prior(2.0 * 1.0 + 0.0 * 0.5, 1.5, SGOffTheTeeRating._prior)
    assert SGOffTheTeeRating().compute(ctx, {}) == pytest.approx(expected)


def test_each_sg_feature_reads_its_own_attribute() -> None:
    today = date(2026, 6, 4)
    r = _make_round(rid=1, sg_ott=1.0, sg_app=2.0, sg_arg=3.0, sg_putt=4.0, sg_total=10.0)
    ctx = FeatureContext(player_id=1, as_of_date=today, rounds=(DatedRound(r, today),))
    # Single round, weight 1.0 → shrink_to_prior(value, 1.0, prior) per category.
    assert SGOffTheTeeRating().compute(ctx, {}) == pytest.approx(
        shrink_to_prior(1.0, 1.0, SGOffTheTeeRating._prior)
    )
    assert SGApproachRating().compute(ctx, {}) == pytest.approx(
        shrink_to_prior(2.0, 1.0, SGApproachRating._prior)
    )
    assert SGAroundTheGreenRating().compute(ctx, {}) == pytest.approx(
        shrink_to_prior(3.0, 1.0, SGAroundTheGreenRating._prior)
    )
    assert SGPuttingRating().compute(ctx, {}) == pytest.approx(
        shrink_to_prior(4.0, 1.0, SGPuttingRating._prior)
    )
    assert SGTotalRating().compute(ctx, {}) == pytest.approx(
        shrink_to_prior(10.0, 1.0, SGTotalRating._prior)
    )


def test_form_index_is_zero_when_recent_equals_baseline() -> None:
    """All rounds identical → recent mean == baseline mean → form == 0."""
    today = date(2026, 6, 4)
    rounds = tuple(
        DatedRound(_make_round(rid=i, sg_total=0.5), date(2026, 1, 1))
        for i in range(20)
    )
    ctx = FeatureContext(player_id=1, as_of_date=today, rounds=rounds)
    assert FormIndex().compute(ctx, {}) == pytest.approx(0.0)


def test_form_index_positive_when_recent_outperforms_baseline() -> None:
    """8 recent strong rounds (sg=2.0), 12 older average rounds (sg=0.0).
    recent_mean = 2.0; baseline (window=50, only 20 rounds) takes all 20:
    baseline_mean = (8 * 2.0 + 12 * 0.0) / 20 = 0.8.
    form_index = 2.0 - 0.8 = 1.2.
    """
    today = date(2026, 6, 4)
    strong = [
        DatedRound(_make_round(rid=i, sg_total=2.0), date(2026, 6, 1))
        for i in range(8)
    ]
    average = [
        DatedRound(_make_round(rid=i + 100, sg_total=0.0), date(2025, 12, 1))
        for i in range(12)
    ]
    ctx = FeatureContext(
        player_id=1, as_of_date=today, rounds=tuple(strong + average)
    )
    assert FormIndex().compute(ctx, {}) == pytest.approx(1.2)


# ---------------------------------------------------------------------------
# v1_baseline composition
# ---------------------------------------------------------------------------


def test_v1_baseline_has_six_features() -> None:
    fs = v1_baseline()
    assert len(fs.features) == 6
    assert {f.name for f in fs.features} == {
        "sg_ott_rating",
        "sg_app_rating",
        "sg_arg_rating",
        "sg_putt_rating",
        "sg_total_rating",
        "form_index",
    }


def test_v1_baseline_registry_runs_end_to_end() -> None:
    fs = v1_baseline()
    registry = FeatureRegistry(fs.features)
    today = date(2026, 6, 4)
    r = _make_round(rid=1, sg_ott=0.5, sg_app=0.5, sg_arg=0.5, sg_putt=0.5, sg_total=2.0)
    ctx = FeatureContext(player_id=1, as_of_date=today, rounds=(DatedRound(r, today),))
    values = registry.compute(ctx)
    # All six features ran.
    assert set(values.keys()) == {f.name for f in fs.features}
    # One round (weight 1.0) shrunk toward the sg_total prior.
    assert values["sg_total_rating"] == pytest.approx(
        shrink_to_prior(2.0, 1.0, SGTotalRating._prior)
    )
    # Single round → recent and baseline windows both contain only it,
    # so form_index is zero.
    assert values["form_index"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Field-relative features (v2)
# ---------------------------------------------------------------------------


def _ctx_with_field(
    *,
    own_sg_total: float,
    field_mean_sg_total: float,
    field_size: int = 100,
    rounds: tuple[DatedRound, ...] = (),
) -> FeatureContext:
    return FeatureContext(
        player_id=1,
        as_of_date=date(2026, 6, 4),
        rounds=rounds,
        field=FieldContext(
            mean_skill={"sg_total_rating": field_mean_sg_total},
            field_size=field_size,
        ),
    )


def test_field_relative_is_margin_over_field_mean() -> None:
    # Player's own sg_total_rating arrives via deps; field mean from context.
    ctx = _ctx_with_field(own_sg_total=1.5, field_mean_sg_total=0.4)
    value = FieldRelativeSGTotal().compute(ctx, {"sg_total_rating": 1.5})
    assert value == pytest.approx(1.1)  # 1.5 − 0.4


def test_field_relative_negative_for_below_field_player() -> None:
    ctx = _ctx_with_field(own_sg_total=-0.3, field_mean_sg_total=0.5)
    value = FieldRelativeSGTotal().compute(ctx, {"sg_total_rating": -0.3})
    assert value == pytest.approx(-0.8)


def test_field_relative_neutral_without_field_context() -> None:
    # No field (single-player extraction) → neutral 0.0 regardless of own skill.
    ctx = FeatureContext(player_id=1, as_of_date=date(2026, 6, 4), rounds=())
    value = FieldRelativeSGTotal().compute(ctx, {"sg_total_rating": 2.0})
    assert value == 0.0


def test_field_strength_returns_field_mean_sg_total() -> None:
    ctx = _ctx_with_field(own_sg_total=1.0, field_mean_sg_total=0.42)
    assert FieldStrength().compute(ctx, {"sg_total_rating": 1.0}) == pytest.approx(0.42)


def test_field_strength_zero_without_field() -> None:
    ctx = FeatureContext(player_id=1, as_of_date=date(2026, 6, 4), rounds=())
    assert FieldStrength().compute(ctx, {"sg_total_rating": 1.0}) == 0.0


def test_round_count_reports_number_of_rounds() -> None:
    today = date(2026, 6, 4)
    rounds = tuple(
        DatedRound(_make_round(rid=i, sg_total=1.0), today) for i in range(7)
    )
    ctx = FeatureContext(player_id=1, as_of_date=today, rounds=rounds)
    assert RoundCount().compute(ctx, {}) == pytest.approx(7.0)


def test_v2_field_relative_has_fourteen_features() -> None:
    fs = v2_field_relative()
    assert len(fs.features) == 14
    names = {f.name for f in fs.features}
    # v2 is a superset of v1.
    assert {f.name for f in v1_baseline().features} <= names
    # Plus the field-relative additions and the volatility estimate.
    assert {
        "field_rel_sg_ott", "field_rel_sg_app", "field_rel_sg_arg",
        "field_rel_sg_putt", "field_rel_sg_total", "field_strength",
        "round_count", "score_volatility",
    } <= names


def test_v2_registry_runs_end_to_end_with_field() -> None:
    """The registry resolves field-relative deps and reads field context."""
    fs = v2_field_relative()
    registry = FeatureRegistry(fs.features)
    today = date(2026, 6, 4)
    r = _make_round(rid=1, sg_ott=0.5, sg_app=0.5, sg_arg=0.5, sg_putt=0.5, sg_total=2.0)
    ctx = FeatureContext(
        player_id=1,
        as_of_date=today,
        rounds=(DatedRound(r, today),),
        field=FieldContext(mean_skill={"sg_total_rating": 0.5}, field_size=50),
    )
    values = registry.compute(ctx)
    assert set(values.keys()) == {f.name for f in fs.features}
    # One round today (weight 1.0) shrunk toward the sg_total prior.
    expected_total = shrink_to_prior(2.0, 1.0, SGTotalRating._prior)
    assert values["sg_total_rating"] == pytest.approx(expected_total)
    assert values["field_rel_sg_total"] == pytest.approx(expected_total - 0.5)
    assert values["field_strength"] == pytest.approx(0.5)
    assert values["round_count"] == pytest.approx(1.0)


def test_v2_hash_differs_from_v1() -> None:
    assert v2_field_relative().hash != v1_baseline().hash


def test_score_volatility_zero_when_too_few_rounds() -> None:
    # Fewer than the 5-round minimum → 0.0 (engine reads as "unknown").
    today = date(2026, 6, 4)
    rounds = tuple(
        DatedRound(_make_round(rid=i, sg_total=float(i)), today) for i in range(4)
    )
    ctx = FeatureContext(player_id=1, as_of_date=today, rounds=rounds)
    assert ScoreVolatility().compute(ctx, {}) == 0.0


def test_score_volatility_zero_for_perfectly_consistent_player() -> None:
    today = date(2026, 6, 4)
    rounds = tuple(
        DatedRound(_make_round(rid=i, sg_total=1.0), today) for i in range(10)
    )
    ctx = FeatureContext(player_id=1, as_of_date=today, rounds=rounds)
    assert ScoreVolatility().compute(ctx, {}) == pytest.approx(0.0)


def test_score_volatility_is_population_std_of_recent_sg_total() -> None:
    # sg_total alternating +2 / -2 over 6 rounds → mean 0, population std 2.0.
    today = date(2026, 6, 4)
    vals = [2.0, -2.0, 2.0, -2.0, 2.0, -2.0]
    rounds = tuple(
        DatedRound(_make_round(rid=i, sg_total=v), date(2026, 6, 1))
        for i, v in enumerate(vals)
    )
    ctx = FeatureContext(player_id=1, as_of_date=today, rounds=rounds)
    assert ScoreVolatility().compute(ctx, {}) == pytest.approx(2.0)


def test_v1_baseline_hash_is_stable() -> None:
    """Re-instantiating v1_baseline must produce the same hash."""
    assert v1_baseline().hash == v1_baseline().hash


def test_decay_math_matches_textbook_formula() -> None:
    """Cross-check exponential_decay against math.exp(-ln(2) * t / hl)."""
    for days, hl in [(30, 60.0), (45, 90.0), (120, 60.0)]:
        expected = math.exp(-math.log(2) * days / hl)
        assert exponential_decay_weight(days, hl) == pytest.approx(expected)
