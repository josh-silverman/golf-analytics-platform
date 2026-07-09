"""Rank-native evaluation harness — measurement only, no model (design §3).

Built and validated in isolation *before* any rank-native model exists, so a
future model is debugged against tooling already known to be correct. Three
independently-testable pieces:

* **Market scoring** (:func:`score_markets`) — given per-player, per-market
  probabilities plus actual outcomes, compute Brier, Brier *skill* (vs a
  base-rate baseline), and Spearman, reusing ``backtest``'s own primitives so
  the numbers are identical to the ``golf_v1`` / DG-standalone benchmarks. This
  is what lets a rank-native model's derived markets be compared apples-to-apples
  with everything measured this project.
* **Ranking metrics** (:func:`ranking_metrics`) — NDCG@k, precision@k, per-event
  Spearman, and the winner's predicted rank, on a ranking-native score.
* **Market derivation** (:func:`derive_markets`) — the five nested market
  probabilities from per-player latent scores by Monte-Carlo, *coherent and
  field-normalized by construction* (every sample has exactly one winner and a
  real cut line). Gumbel noise = Plackett-Luce sampling; Gaussian noise =
  strength+variance simulation.

The three market/ranking conventions match the rest of the app: markets are the
nested set win ⊆ top-5 ⊆ top-10 ⊆ top-20 ⊆ make-cut; a higher latent score means
a better (lower-numbered) finish.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import numpy as np

from app.ml.backtest import _bootstrap_skill_ci, _brier, _spearman

if TYPE_CHECKING:
    from collections.abc import Sequence

    from numpy.typing import NDArray


# Nested market keys, narrowest → widest, matching the prediction service.
MARKET_KEYS: tuple[str, ...] = (
    "win_prob",
    "top_5_prob",
    "top_10_prob",
    "top_20_prob",
    "make_cut_prob",
)

# Rank cutoff (1-based, inclusive) that defines each *position* market. make-cut
# has no fixed cutoff (it depends on the event's cut line), so it is absent here
# and handled separately from an explicit cut line.
_MARKET_CUTOFF: dict[str, int] = {
    "win_prob": 1,
    "top_5_prob": 5,
    "top_10_prob": 10,
    "top_20_prob": 20,
}

# NDCG relevance tiers keyed to the five markets, so ranking quality is scored on
# exactly the distinctions the product cares about (winner > top-5 > … > cut).
_REL_WINNER = 5
_REL_TOP_5 = 4
_REL_TOP_10 = 3
_REL_TOP_20 = 2
_REL_MADE_CUT = 1
_REL_MISSED_CUT = 0


def market_labels(final_position: int | None, made_cut: bool) -> dict[str, int]:
    """Binary actual-outcome labels for the five markets.

    Matches ``training.labels_from_entry``: a missed-cut player has
    ``final_position is None`` and therefore 0 for every position market, and a
    made-cut player always carries a position. ``make_cut`` is independent of the
    position buckets.
    """
    pos = final_position
    return {
        "win_prob": 1 if pos == 1 else 0,
        "top_5_prob": 1 if pos is not None and pos <= 5 else 0,
        "top_10_prob": 1 if pos is not None and pos <= 10 else 0,
        "top_20_prob": 1 if pos is not None and pos <= 20 else 0,
        "make_cut_prob": 1 if made_cut else 0,
    }


def finish_relevance(final_position: int | None, made_cut: bool) -> int:
    """Graded NDCG relevance (0–5) from a finish, tiered to the five markets."""
    if not made_cut or final_position is None:
        return _REL_MISSED_CUT
    if final_position == 1:
        return _REL_WINNER
    if final_position <= 5:
        return _REL_TOP_5
    if final_position <= 10:
        return _REL_TOP_10
    if final_position <= 20:
        return _REL_TOP_20
    return _REL_MADE_CUT


# ---------------------------------------------------------------------------
# Market scoring — reproduces the benchmark numbers exactly
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MarketScore:
    """Out-of-sample quality for one market, pooled over the test rows.

    ``spearman`` is the mean over events of Spearman(prob, −finish), matching the
    ranking metric the golf_v1 backtest reports. CI bounds are the 90%
    block-bootstrap interval on the skill score (``nan`` when not requested).
    """

    outcome_key: str
    n: int
    base_rate: float
    brier: float
    brier_skill_score: float
    spearman: float
    brier_skill_score_ci_lower: float = float("nan")
    brier_skill_score_ci_upper: float = float("nan")


@dataclass(frozen=True)
class MarketRow:
    """One scored player in one event."""

    player_id: int
    placement: float  # resolved finish rank (missed cut → a worst-tail value)
    labels: dict[str, int]  # market → actual 0/1
    probs: dict[str, float]  # market → predicted probability


def score_markets(
    events: Sequence[Sequence[MarketRow]],
    *,
    bootstrap_reps: int = 0,
    bootstrap_ci: float = 0.90,
    bootstrap_seed: int = 0,
) -> dict[str, MarketScore]:
    """Brier / Brier-skill / Spearman per market, pooled across events.

    Point estimates pool every row; Spearman averages per-event Spearman over
    events with ≥3 scored players (the backtest convention). Reuses ``_brier`` /
    ``_spearman`` so results match the established benchmarks to floating point.
    Set ``bootstrap_reps > 0`` for the block-bootstrap skill CI (event-resampled).
    """
    scored = [ev for ev in events if ev]
    out: dict[str, MarketScore] = {}
    for market in MARKET_KEYS:
        y_events: list[NDArray[np.float64]] = []
        p_events: list[NDArray[np.float64]] = []
        spearmans: list[float] = []
        for ev in scored:
            y = np.array([o.labels[market] for o in ev], dtype=np.float64)
            p = np.array([o.probs[market] for o in ev], dtype=np.float64)
            place = np.array([o.placement for o in ev], dtype=np.float64)
            y_events.append(y)
            p_events.append(p)
            if len(ev) >= 3:
                spearmans.append(_spearman(p, -place))
        if not y_events:
            continue
        y_all = np.concatenate(y_events)
        p_all = np.concatenate(p_events)
        base_rate = float(np.mean(y_all))
        base_brier = float(np.mean((base_rate - y_all) ** 2))
        brier = _brier(y_all, p_all)
        skill = 0.0 if base_brier == 0.0 else 1.0 - brier / base_brier
        lo, hi = (
            _bootstrap_skill_ci(
                y_events, p_events,
                n_reps=bootstrap_reps, ci=bootstrap_ci, seed=bootstrap_seed,
            )
            if bootstrap_reps > 0
            else (float("nan"), float("nan"))
        )
        out[market] = MarketScore(
            outcome_key=market,
            n=len(y_all),
            base_rate=base_rate,
            brier=brier,
            brier_skill_score=skill,
            spearman=float(np.mean(spearmans)) if spearmans else 0.0,
            brier_skill_score_ci_lower=lo,
            brier_skill_score_ci_upper=hi,
        )
    return out


# ---------------------------------------------------------------------------
# Ranking metrics — on a ranking-native score (higher = better finish)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RankRow:
    """One player's ranking-native prediction and actual finish."""

    player_id: int
    score: float  # higher = predicted better (lower-numbered) finish
    placement: float  # actual finish rank (missed cut → worst-tail value)
    final_position: int | None
    made_cut: bool


@dataclass(frozen=True)
class RankingReport:
    """Aggregate ranking quality over the test events."""

    n_events: int
    spearman: float
    mean_winner_rank: float
    ndcg: dict[int, float]
    precision: dict[int, float]


def _dcg(relevances: NDArray[np.float64]) -> float:
    """Discounted cumulative gain with the standard ``2**rel - 1`` gain."""
    if len(relevances) == 0:
        return 0.0
    discounts = 1.0 / np.log2(np.arange(2, len(relevances) + 2))
    return float(np.sum((2.0**relevances - 1.0) * discounts))


def _ndcg_at_k(scores: NDArray[np.float64], rels: NDArray[np.float64], k: int) -> float:
    """NDCG@k: DCG of the predicted top-k vs the ideal ordering's top-k."""
    kk = min(k, len(scores))
    order = np.argsort(-scores, kind="mergesort")
    gains = rels[order][:kk]
    ideal = np.sort(rels)[::-1][:kk]
    ideal_dcg = _dcg(ideal)
    return _dcg(gains) / ideal_dcg if ideal_dcg > 0.0 else 0.0


def _precision_at_k(
    scores: NDArray[np.float64], placement: NDArray[np.float64], k: int
) -> float:
    """Fraction of the predicted top-k that actually finished in the top-k."""
    kk = min(k, len(scores))
    if kk == 0:
        return 0.0
    pred_top = set(np.argsort(-scores, kind="mergesort")[:kk].tolist())
    actual_top = set(np.argsort(placement, kind="mergesort")[:kk].tolist())
    return len(pred_top & actual_top) / kk


def ranking_metrics(
    events: Sequence[Sequence[RankRow]],
    *,
    ks: tuple[int, ...] = (5, 10, 20),
) -> RankingReport:
    """NDCG@k, precision@k, per-event Spearman, and mean winner rank."""
    scored = [ev for ev in events if len(ev) >= 3]
    spearmans: list[float] = []
    winner_ranks: list[int] = []
    ndcg: dict[int, list[float]] = {k: [] for k in ks}
    precision: dict[int, list[float]] = {k: [] for k in ks}

    for ev in scored:
        scores = np.array([o.score for o in ev], dtype=np.float64)
        place = np.array([o.placement for o in ev], dtype=np.float64)
        rels = np.array(
            [finish_relevance(o.final_position, o.made_cut) for o in ev],
            dtype=np.float64,
        )
        spearmans.append(_spearman(scores, -place))
        order = np.argsort(-scores, kind="mergesort")
        winners = [i for i, o in enumerate(ev) if o.final_position == 1]
        if winners:
            winner_ranks.append(int(np.where(order == winners[0])[0][0]) + 1)
        for k in ks:
            ndcg[k].append(_ndcg_at_k(scores, rels, k))
            precision[k].append(_precision_at_k(scores, place, k))

    return RankingReport(
        n_events=len(scored),
        spearman=float(np.mean(spearmans)) if spearmans else 0.0,
        mean_winner_rank=float(np.mean(winner_ranks)) if winner_ranks else 0.0,
        ndcg={k: float(np.mean(v)) if v else 0.0 for k, v in ndcg.items()},
        precision={k: float(np.mean(v)) if v else 0.0 for k, v in precision.items()},
    )


# ---------------------------------------------------------------------------
# Market derivation — coherent & field-normalized by construction
# ---------------------------------------------------------------------------


def derive_markets(
    scores: NDArray[np.float64],
    *,
    cut_line: int,
    method: Literal["gumbel", "gaussian"] = "gumbel",
    scale: float = 1.0,
    n_sims: int = 10_000,
    seed: int = 0,
) -> NDArray[np.float64]:
    """Per-player nested market probabilities from latent scores, by Monte-Carlo.

    ``scores`` are per-player latent strengths (higher = better). Each of
    ``n_sims`` samples perturbs the scores (``gumbel`` → Plackett-Luce sampling;
    ``gaussian`` → strength+variance simulation with std ``scale``), ranks the
    field, and tallies the nested markets. ``cut_line`` is the last made-cut rank
    (1-based). Returns an ``(n_players, 5)`` array in ``MARKET_KEYS`` order.

    Coherent and field-normalized *by construction*: every sample has exactly one
    winner, five top-5s, …, and ``cut_line`` made-cutters, so per player the five
    probabilities are monotone and each market sums across the field to its true
    total — no ``coherent_outcomes`` / ``normalize_field`` patch needed.
    """
    n = len(scores)
    if n == 0:
        return np.zeros((0, len(MARKET_KEYS)), dtype=np.float64)
    rng = np.random.default_rng(seed)
    if method == "gumbel":
        noise = rng.gumbel(0.0, 1.0, size=(n_sims, n))
    else:
        noise = rng.normal(0.0, scale, size=(n_sims, n))
    perturbed = scores[None, :] + noise
    # rank 1 = best = highest perturbed score. argsort desc gives the ordering;
    # a second argsort turns it into each player's 1-based rank per sample.
    order = np.argsort(-perturbed, axis=1, kind="stable")
    ranks = np.empty_like(order)
    rows = np.arange(n_sims)[:, None]
    ranks[rows, order] = np.arange(1, n + 1)[None, :]

    probs = np.empty((n, len(MARKET_KEYS)), dtype=np.float64)
    for j, market in enumerate(MARKET_KEYS):
        cutoff = _MARKET_CUTOFF.get(market, cut_line)
        probs[:, j] = np.mean(ranks <= cutoff, axis=0)
    return probs


# ---------------------------------------------------------------------------
# Paired-delta bootstrap — the comparison layer (design §3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PairedDelta:
    """Paired per-event delta (model A − model B) with a block-bootstrap CI."""

    metric: str
    point: float
    ci_lower: float
    ci_upper: float


def paired_delta_skill(
    events: Sequence[Sequence[MarketRow]],
    market: str,
    probs_a: str,
    probs_b: str,
    *,
    n_reps: int = 2000,
    ci: float = 0.90,
    seed: int = 0,
) -> PairedDelta:
    """Paired block-bootstrap CI on the Brier-skill delta (A − B) for one market.

    ``probs_a`` / ``probs_b`` name two probability keys carried on each row's
    ``probs`` dict (e.g. two competitors stored side by side). Resamples whole
    events; both competitors are scored on the identical resampled rows each rep.
    Positive = A better.
    """
    scored = [ev for ev in events if ev]
    ev_y = [np.array([o.labels[market] for o in ev], dtype=np.float64) for ev in scored]
    ev_a = [np.array([o.probs[probs_a] for o in ev], dtype=np.float64) for ev in scored]
    ev_b = [np.array([o.probs[probs_b] for o in ev], dtype=np.float64) for ev in scored]

    def delta(idx: Sequence[int]) -> float:
        y = np.concatenate([ev_y[i] for i in idx])
        base = float(np.mean((np.mean(y) - y) ** 2))
        if base == 0.0:
            return 0.0
        a = _brier(y, np.concatenate([ev_a[i] for i in idx]))
        b = _brier(y, np.concatenate([ev_b[i] for i in idx]))
        return (b - a) / base  # skill_a - skill_b

    all_idx = list(range(len(scored)))
    point = delta(all_idx)
    rng = np.random.default_rng(seed)
    reps = rng.integers(0, len(scored), size=(n_reps, len(scored)))
    dist = np.array([delta(reps[i]) for i in range(n_reps)], dtype=np.float64)
    half = (1.0 - ci) / 2.0
    return PairedDelta(
        metric=f"skill_delta[{market}]",
        point=point,
        ci_lower=float(np.quantile(dist, half)),
        ci_upper=float(np.quantile(dist, 1.0 - half)),
    )
