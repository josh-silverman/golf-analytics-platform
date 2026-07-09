"""Strength+variance rank-native model — MVP (research track rank_v1).

The minimum viable version of the model recommended in
``docs/rank-native-model-design.md`` §1, built to produce a *first real number*
through the validated evaluation harness — not a polished model.

  * ``mu``    = ``sg_total_rating`` — the existing time-decayed per-round SG skill
                (strokes-gained units). No new estimation machinery. Because a
                field is ranked internally, absolute and field-relative SG give
                identical orderings, so the absolute rating is used directly.
  * ``sigma`` = ``score_volatility`` — the existing round-to-round SG-total std,
                the Monte-Carlo input the design flagged as extracted-but-unused.
                A thin history returns 0 → fall back to the field median (the
                behaviour ``ScoreVolatility``'s own docstring specifies).

Each player's tournament is simulated as ``N_ROUNDS`` i.i.d. ``Normal(mu, sigma)``
per-round SG draws; the field is ranked by 4-round SG total; the five nested
markets are read from the simulated finish distribution — **coherent and
field-normalized by construction** (every sample has one winner, five top-5s, …,
and ``cut_line`` made-cutters), so no ``coherent_outcomes`` / ``normalize_field``
patch is needed.

Deliberately the simplest thing that runs: no course effects, no round-to-round
correlation, no field interaction. ``make_cut`` is approximated as *finishing in
the top ``cut_line`` by 4-round total* rather than the true 36-hole cut — a known
simplification to revisit only after the first number is in.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from numpy.typing import NDArray

# Nested market cutoffs (win / top-5 / top-10 / top-20 / make-cut), matching
# ``evaluation.MARKET_KEYS`` order. make-cut uses the per-event cut line.
N_ROUNDS = 4
_FIXED_CUTOFFS: tuple[int, ...] = (1, 5, 10, 20)

# Floor on the per-player round-SG std so a degenerate (near-zero) history can
# never collapse the simulation to a deterministic order.
_SIGMA_FLOOR = 0.5
# Last-resort field std when a whole field somehow has no positive volatility.
_SIGMA_DEFAULT = 2.0


def resolve_sigma(score_volatility: NDArray[np.float64]) -> NDArray[np.float64]:
    """Per-player round-SG std, replacing 0 (thin history) with the field median.

    ``ScoreVolatility`` emits 0.0 for players with too few rounds; the simulation
    reads that as "unknown" and substitutes the field's median positive volatility
    so a thin history never produces a degenerate zero-variance draw.
    """
    sigma = np.asarray(score_volatility, dtype=np.float64)
    positive = sigma[sigma > 0.0]
    fallback = float(np.median(positive)) if positive.size else _SIGMA_DEFAULT
    filled = np.where(sigma > 0.0, sigma, fallback)
    return np.maximum(filled, _SIGMA_FLOOR)


def simulate_markets(
    mu: NDArray[np.float64],
    sigma: NDArray[np.float64],
    *,
    cut_line: int,
    n_sims: int = 10_000,
    seed: int = 0,
) -> NDArray[np.float64]:
    """Five nested market probabilities per player from a strength+variance sim.

    ``mu`` / ``sigma`` are per-player round-SG mean and std; ``cut_line`` is the
    number of players who make the cut (the rank threshold for ``make_cut``).
    Returns an ``(n_players, 5)`` array in win / top-5 / top-10 / top-20 /
    make-cut order.
    """
    n = len(mu)
    if n == 0:
        return np.zeros((0, len(_FIXED_CUTOFFS) + 1), dtype=np.float64)
    rng = np.random.default_rng(seed)
    sig = resolve_sigma(sigma)
    mu = np.asarray(mu, dtype=np.float64)

    # N_ROUNDS i.i.d. per-round SG draws per player per sim; sum to a tournament
    # total. Higher total SG = better (lower-numbered) finish.
    rounds = rng.normal(
        loc=mu[None, :, None],
        scale=sig[None, :, None],
        size=(n_sims, n, N_ROUNDS),
    )
    totals = rounds.sum(axis=2)  # (n_sims, n)

    # Turn each sim's ordering into 1-based ranks (rank 1 = best total).
    order = np.argsort(-totals, axis=1, kind="stable")
    ranks = np.empty_like(order)
    rows = np.arange(n_sims)[:, None]
    ranks[rows, order] = np.arange(1, n + 1)[None, :]

    cutoffs = (*_FIXED_CUTOFFS, cut_line)
    probs = np.empty((n, len(cutoffs)), dtype=np.float64)
    for j, cutoff in enumerate(cutoffs):
        probs[:, j] = np.mean(ranks <= cutoff, axis=0)
    return probs
