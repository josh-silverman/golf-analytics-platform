"""Betting edge — board vs. market divergence for the Market Comparison page.

Estimates the true probability of an outcome (the served model's board),
obtains the book's implied probability (American odds, vig removed), and
reports the divergence (``edge = model_prob - implied_prob``). This module no
longer sizes a stake or computes expected value: the frontend it serves was
narrowed from a betting tool to a market-comparison view (no EV, no Kelly,
no +EV recommendation), and the fields that math produced were removed here
to match — see git history for ``ev_per_dollar``/``kelly``/
``positive_ev_lines`` if that math is ever needed again.

"Betting edge is meaningless without well-calibrated probabilities" (doc 01 §1)
— that is exactly why calibration lands before this module.

Odds source. When the data provider surfaces real sportsbook odds (DataGolf's
``betting-tools/outrights``), we use the consensus line per player and remove
the vig by *field normalization*: a book's implied probabilities across the
field sum to more than the true total (1 winner, 5 top-5s, …); scaling them
back to that theoretical total strips the margin without assuming a flat vig.
Players the book doesn't price — and every market when no feed is configured —
fall back to a synthetic line generated from the model's own probability with
a realistic vig, so every player still has an ``odds_source`` and the frontend's
real-vs-synthetic coverage count (how many of the field have a real price) stays
accurate even though it no longer displays the synthetic line's own numbers.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.predictions import PlayerOutcome

# Standard sportsbook vigourish margin: the book takes ~8-12% of every dollar
# wagered as margin; 10% is a reasonable mid-market assumption.
DEFAULT_VIG_MARGIN = 0.10


# Theoretical sum of true probabilities across a full field, per market. A
# book's de-vigged implied probabilities must sum to this (one winner, five
# top-5 finishers, …). ``make_cut`` has no fixed total (depends on the cut
# rule), so it de-vigs with a flat margin instead.
_MARKET_TARGET_SUM: dict[str, float] = {
    "win_prob": 1.0,
    "top_5_prob": 5.0,
    "top_10_prob": 10.0,
    "top_20_prob": 20.0,
}


@dataclass(frozen=True)
class BettingLine:
    """One player's edge analysis for a single outcome market."""

    player_id: int
    player_name: str
    # Our model's probability estimate (the served board)
    model_prob: float
    # The book's implied probability (after removing vig)
    implied_prob: float
    # Raw American odds as displayed in the book
    american_odds: int
    # Edge: positive means the board's probability exceeds the book's
    edge: float
    # "datagolf" if this line came from a real sportsbook consensus, else "model"
    odds_source: str = "model"


@dataclass(frozen=True)
class BettingBoard:
    """Aggregated edge lines for an entire tournament field."""

    tournament_id: int
    tournament_name: str
    outcome_key: str  # e.g. "win_prob"
    lines: tuple[BettingLine, ...]
    # "datagolf" if any line used a real sportsbook consensus, else "model".
    odds_source: str = "model"


# ---------------------------------------------------------------------------
# Probability / odds conversions
# ---------------------------------------------------------------------------


def american_to_implied_prob(odds: int, *, vig_margin: float = 0.0) -> float:
    """Convert American odds to fair implied probability.

    ``vig_margin`` strips the book's take-rate so we compare apples to
    apples with our model's true probability estimate.
    """
    raw = 100.0 / (odds + 100.0) if odds >= 0 else (-odds) / (-odds + 100.0)
    return raw / (1.0 + vig_margin)


def prob_to_american(p: float) -> int:
    """Convert a fair probability to the nearest American odds integer."""
    if p <= 0.0 or p >= 1.0:
        raise ValueError(f"Probability must be in (0, 1), got {p}")
    if p >= 0.5:
        return round(-p / (1.0 - p) * 100)
    return round((1.0 - p) / p * 100)


# ---------------------------------------------------------------------------
# Mock odds generation
# ---------------------------------------------------------------------------


def _generate_mock_american_odds(
    sim_prob: float,
    *,
    noise_std: float = 0.03,
    vig_margin: float = DEFAULT_VIG_MARGIN,
    rng_state: float = 0.0,
) -> int:
    """Generate a realistic mock American odds line for ``sim_prob``.

    A small deterministic perturbation (seeded from player position in the
    field) simulates the book pricing slightly differently from our model,
    creating genuine +EV and -EV lines rather than uniform zero edge.
    The vig is baked in by compressing the probability toward 0.5.
    """
    # Perturb with deterministic noise (no random state needed — the position
    # in the sorted field acts as a seed via rng_state).
    perturbed = sim_prob + noise_std * math.sin(rng_state * 17.3)
    # Clamp to a valid probability range before adding vig.
    perturbed = max(0.005, min(0.97, perturbed))
    # Apply vig by scaling the probability upward (book overestimates true prob).
    book_prob = perturbed * (1.0 + vig_margin)
    book_prob = max(0.005, min(0.995, book_prob))
    return prob_to_american(book_prob)


# ---------------------------------------------------------------------------
# Real-odds de-vigging
# ---------------------------------------------------------------------------


def devig_field_odds(
    real_odds: dict[int, int],
    *,
    outcome_key: str,
    vig_margin: float = DEFAULT_VIG_MARGIN,
) -> dict[int, float]:
    """Convert real American odds → fair (de-vigged) implied probabilities.

    For markets with a known theoretical total (win, top-N) we normalize the
    field's raw implied probabilities to that total, which strips the book's
    margin without assuming it's flat. ``make_cut`` has no fixed total, so it
    falls back to dividing out a flat vig margin.

    Public because the closing-line archive de-vigs captured book prices with
    exactly this function (``services/closing_line_archive``); the market
    baseline the forward record is graded against and the price the betting
    board quotes must come from the same math, or the two disagree silently.
    """
    raw = {pid: american_to_implied_prob(odds, vig_margin=0.0) for pid, odds in real_odds.items()}
    target = _MARKET_TARGET_SUM.get(outcome_key)
    if target is None:
        # No theoretical total — strip a flat margin instead.
        return {pid: p / (1.0 + vig_margin) for pid, p in raw.items()}
    total = sum(raw.values())
    if total <= 0.0:
        return raw
    scale = target / total
    return {pid: min(0.999, p * scale) for pid, p in raw.items()}


# ---------------------------------------------------------------------------
# Board assembly
# ---------------------------------------------------------------------------


def build_betting_board(
    outcomes: tuple[PlayerOutcome, ...],
    *,
    tournament_id: int,
    tournament_name: str,
    outcome_key: str = "win_prob",
    vig_margin: float = DEFAULT_VIG_MARGIN,
    real_odds: dict[int, int] | None = None,
) -> BettingBoard:
    """Build a full betting board from the served model's outcomes.

    When ``real_odds`` (player_id → consensus American odds) is supplied, each
    matching player is priced against the de-vigged real line; everyone else
    falls back to a synthetic line. Lines are returned sorted by edge
    descending (largest board-vs-market divergence first). ``board.odds_source``
    is ``"datagolf"`` if any real line was used.
    """

    def _get_prob(o: PlayerOutcome) -> float:
        return getattr(o, outcome_key, 0.0)

    devigged: dict[int, float] = (
        devig_field_odds(real_odds, outcome_key=outcome_key, vig_margin=vig_margin)
        if real_odds
        else {}
    )
    used_real = False

    lines: list[BettingLine] = []
    for i, outcome in enumerate(outcomes):
        model_prob = _get_prob(outcome)
        if model_prob < 0.001:
            # Effectively 0 — skip to avoid degenerate odds.
            continue

        real_implied = devigged.get(outcome.player_id)
        if real_implied is not None and real_odds is not None:
            implied = real_implied
            amer = real_odds[outcome.player_id]
            source = "datagolf"
            used_real = True
        else:
            amer = _generate_mock_american_odds(
                model_prob, vig_margin=vig_margin, rng_state=float(i)
            )
            implied = american_to_implied_prob(amer, vig_margin=vig_margin)
            source = "model"

        edge = model_prob - implied
        lines.append(
            BettingLine(
                player_id=outcome.player_id,
                player_name=outcome.player_name,
                model_prob=model_prob,
                implied_prob=implied,
                american_odds=amer,
                edge=edge,
                odds_source=source,
            )
        )

    # Sort by edge descending: the largest board-vs-market divergences first.
    lines.sort(key=lambda bl: bl.edge, reverse=True)
    return BettingBoard(
        tournament_id=tournament_id,
        tournament_name=tournament_name,
        outcome_key=outcome_key,
        lines=tuple(lines),
        odds_source="datagolf" if used_real else "model",
    )
