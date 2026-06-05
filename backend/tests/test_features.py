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
)
from app.features.feature_sets import v1_baseline
from app.features.player import (
    FormIndex,
    SGApproachRating,
    SGAroundTheGreenRating,
    SGOffTheTeeRating,
    SGPuttingRating,
    SGTotalRating,
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
    bumped_feature.version = 2
    bumped = FeatureSet("v1", [bumped_feature])
    assert base.hash != bumped.hash


# ---------------------------------------------------------------------------
# Player features
# ---------------------------------------------------------------------------


def test_sg_rating_empty_rounds_returns_zero() -> None:
    feature = SGOffTheTeeRating()
    ctx = FeatureContext(player_id=1, as_of_date=date(2026, 6, 4), rounds=())
    assert feature.compute(ctx, {}) == 0.0


def test_sg_rating_uniform_rounds_returns_their_value() -> None:
    """Three identical rounds played on the same day → that exact value."""
    rounds = tuple(
        DatedRound(_make_round(rid=i, sg_ott=1.2), date(2026, 6, 1))
        for i in range(3)
    )
    ctx = FeatureContext(player_id=1, as_of_date=date(2026, 6, 4), rounds=rounds)
    assert SGOffTheTeeRating().compute(ctx, {}) == pytest.approx(1.2)


def test_sg_rating_weights_recent_round_more_than_old_round() -> None:
    """One round today (sg_ott=2), one round 60 days ago (sg_ott=0).
    With 60-day half-life, weights are 1.0 and 0.5, so the rating should
    be (2*1 + 0*0.5) / (1 + 0.5) = 4/3 ≈ 1.333.
    """
    today = date(2026, 6, 4)
    rounds = (
        DatedRound(_make_round(rid=1, sg_ott=2.0), today),
        DatedRound(_make_round(rid=2, sg_ott=0.0), date(2026, 4, 5)),  # 60 days ago
    )
    ctx = FeatureContext(player_id=1, as_of_date=today, rounds=rounds)
    assert SGOffTheTeeRating().compute(ctx, {}) == pytest.approx(4.0 / 3.0)


def test_each_sg_feature_reads_its_own_attribute() -> None:
    today = date(2026, 6, 4)
    r = _make_round(rid=1, sg_ott=1.0, sg_app=2.0, sg_arg=3.0, sg_putt=4.0, sg_total=10.0)
    ctx = FeatureContext(player_id=1, as_of_date=today, rounds=(DatedRound(r, today),))
    assert SGOffTheTeeRating().compute(ctx, {}) == pytest.approx(1.0)
    assert SGApproachRating().compute(ctx, {}) == pytest.approx(2.0)
    assert SGAroundTheGreenRating().compute(ctx, {}) == pytest.approx(3.0)
    assert SGPuttingRating().compute(ctx, {}) == pytest.approx(4.0)
    assert SGTotalRating().compute(ctx, {}) == pytest.approx(10.0)


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
    # With one round and 60-day half-life, sg_X_rating == sg_X value.
    assert values["sg_total_rating"] == pytest.approx(2.0)
    # Single round → recent and baseline windows both contain only it,
    # so form_index is zero.
    assert values["form_index"] == pytest.approx(0.0)


def test_v1_baseline_hash_is_stable() -> None:
    """Re-instantiating v1_baseline must produce the same hash."""
    assert v1_baseline().hash == v1_baseline().hash


def test_decay_math_matches_textbook_formula() -> None:
    """Cross-check exponential_decay against math.exp(-ln(2) * t / hl)."""
    for days, hl in [(30, 60.0), (45, 90.0), (120, 60.0)]:
        expected = math.exp(-math.log(2) * days / hl)
        assert exponential_decay_weight(days, hl) == pytest.approx(expected)
