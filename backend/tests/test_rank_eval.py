"""Sanity checks for the rank_v1 evaluation harness (measurement-only).

These validate the harness against inputs whose correct answer is known, so the
tooling is proven before any rank-native model is built on it:
  * a perfect ranking scores maximally on every metric,
  * a reversed ranking scores minimally,
  * derived markets are coherent and field-normalized by construction,
  * market scoring reproduces a hand-computed Brier/skill/Spearman.
The reproduction of the real DG-standalone benchmark numbers is a separate,
data-backed validation run outside the unit-test suite.
"""

from __future__ import annotations

import numpy as np

from app.ml.rank_v1.evaluation import (
    MARKET_KEYS,
    MarketRow,
    RankRow,
    derive_markets,
    market_labels,
    ranking_metrics,
    score_markets,
)


def _rank_event(order_by_score: list[int]) -> list[RankRow]:
    """Build one event where player i finished in position i+1 (1 = winner)."""
    n = len(order_by_score)
    rows = []
    for pid in range(n):
        pos = pid + 1
        rows.append(
            RankRow(
                player_id=pid,
                score=float(order_by_score[pid]),
                placement=float(pos),
                final_position=pos,
                made_cut=pos <= n,  # everyone "made cut" in this synthetic field
            )
        )
    return rows


def test_perfect_ranking_scores_maximally() -> None:
    # score = -position → higher score = better finish, exactly aligned.
    n = 30
    event = [
        RankRow(pid, score=-(pid + 1), placement=float(pid + 1),
                final_position=pid + 1, made_cut=True)
        for pid in range(n)
    ]
    r = ranking_metrics([event])
    assert r.spearman > 0.999
    assert r.mean_winner_rank == 1.0
    for k in (5, 10, 20):
        assert abs(r.ndcg[k] - 1.0) < 1e-9
        assert abs(r.precision[k] - 1.0) < 1e-9


def test_reversed_ranking_scores_minimally() -> None:
    n = 30
    event = [
        RankRow(pid, score=float(pid + 1), placement=float(pid + 1),
                final_position=pid + 1, made_cut=True)
        for pid in range(n)
    ]
    r = ranking_metrics([event])
    assert r.spearman < -0.999
    assert r.mean_winner_rank == float(n)  # winner predicted dead last
    assert r.precision[5] == 0.0


def test_random_ranking_near_baseline() -> None:
    rng = np.random.default_rng(0)
    events = []
    for _ in range(200):
        n = 60
        scores = rng.normal(size=n)
        events.append([
            RankRow(pid, score=float(scores[pid]), placement=float(pid + 1),
                    final_position=pid + 1, made_cut=True)
            for pid in range(n)
        ])
    r = ranking_metrics(events)
    assert abs(r.spearman) < 0.05  # no ranking information
    assert r.precision[5] < 0.2


def test_derived_markets_coherent_and_field_normalized() -> None:
    rng = np.random.default_rng(1)
    scores = rng.normal(size=50)
    cut_line = 30
    probs = derive_markets(scores, cut_line=cut_line, n_sims=20_000, seed=3)
    # Coherence: win <= top5 <= top10 <= top20 <= make_cut for every player.
    for row in probs:
        assert np.all(np.diff(row) >= -1e-9)
        assert np.all((row >= 0.0) & (row <= 1.0))
    # Field-normalized by construction: each position market sums to its total.
    sums = probs.sum(axis=0)
    assert abs(sums[MARKET_KEYS.index("win_prob")] - 1.0) < 1e-9
    assert abs(sums[MARKET_KEYS.index("top_5_prob")] - 5.0) < 1e-9
    assert abs(sums[MARKET_KEYS.index("top_20_prob")] - 20.0) < 1e-9
    assert abs(sums[MARKET_KEYS.index("make_cut_prob")] - cut_line) < 1e-9


def test_derived_markets_dominant_player_wins() -> None:
    scores = np.array([100.0, 0.0, 0.0, 0.0, 0.0])  # player 0 hugely strongest
    probs = derive_markets(scores, cut_line=3, n_sims=5_000, seed=0)
    assert probs[0, MARKET_KEYS.index("win_prob")] > 0.999


def test_market_labels_match_convention() -> None:
    assert market_labels(1, True) == {
        "win_prob": 1, "top_5_prob": 1, "top_10_prob": 1,
        "top_20_prob": 1, "make_cut_prob": 1,
    }
    assert market_labels(None, False) == {
        "win_prob": 0, "top_5_prob": 0, "top_10_prob": 0,
        "top_20_prob": 0, "make_cut_prob": 0,
    }
    assert market_labels(12, True)["top_10_prob"] == 0
    assert market_labels(12, True)["top_20_prob"] == 1


def test_score_markets_matches_hand_computation() -> None:
    # Two events, make-cut only, hand-checkable.
    def row(pid: int, prob: float, made: bool, pos: int | None) -> MarketRow:
        return MarketRow(
            player_id=pid,
            placement=float(pos if pos is not None else 99),
            labels=market_labels(pos, made),
            probs=dict.fromkeys(MARKET_KEYS, prob),
        )

    ev1 = [row(0, 0.9, True, 3), row(1, 0.4, False, None), row(2, 0.8, True, 7)]
    ev2 = [row(3, 0.2, False, None), row(4, 0.7, True, 1), row(5, 0.6, True, 15)]
    scores = score_markets([ev1, ev2])
    mc = scores["make_cut_prob"]
    y = np.array([1, 0, 1, 0, 1, 1], dtype=float)
    p = np.array([0.9, 0.4, 0.8, 0.2, 0.7, 0.6], dtype=float)
    assert mc.n == 6
    assert abs(mc.base_rate - y.mean()) < 1e-12
    assert abs(mc.brier - float(np.mean((p - y) ** 2))) < 1e-12
    base_brier = float(np.mean((y.mean() - y) ** 2))
    assert abs(mc.brier_skill_score - (1.0 - mc.brier / base_brier)) < 1e-12
