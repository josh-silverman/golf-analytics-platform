"""Unit tests for app.services.betting.

Covers the pure functions (odds conversion, Kelly, EV) and the full
build_betting_board() assembler.  No IO, no FastAPI — these run instantly.
"""

from __future__ import annotations

import pytest

from app.services.betting import (
    MIN_EDGE,
    BettingBoard,
    american_to_implied_prob,
    build_betting_board,
    ev_per_dollar,
    kelly,
    prob_to_american,
)
from app.services.predictions import PlayerOutcome

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_outcome(
    player_id: int = 1,
    player_name: str = "Test Player",
    win_prob: float = 0.15,
    top_5_prob: float = 0.40,
    top_10_prob: float = 0.60,
    top_20_prob: float = 0.75,
    make_cut_prob: float = 0.88,
) -> PlayerOutcome:
    return PlayerOutcome(
        player_id=player_id,
        player_name=player_name,
        win_prob=win_prob,
        top_5_prob=top_5_prob,
        top_10_prob=top_10_prob,
        top_20_prob=top_20_prob,
        make_cut_prob=make_cut_prob,
    )


# ---------------------------------------------------------------------------
# american_to_implied_prob
# ---------------------------------------------------------------------------


class TestAmericanToImpliedProb:
    def test_even_money(self) -> None:
        # +100 should be 50% implied probability (no vig).
        prob = american_to_implied_prob(100, vig_margin=0.0)
        assert abs(prob - 0.5) < 1e-9

    def test_favourite_negative_odds(self) -> None:
        # -200 means risk $200 to win $100 → raw = 200/300 ≈ 0.6667
        prob = american_to_implied_prob(-200, vig_margin=0.0)
        assert abs(prob - 2 / 3) < 1e-9

    def test_underdog_positive_odds(self) -> None:
        # +300 means risk $100 to win $300 → raw = 100/400 = 0.25
        prob = american_to_implied_prob(300, vig_margin=0.0)
        assert abs(prob - 0.25) < 1e-9

    def test_vig_reduces_implied_prob(self) -> None:
        # With vig the raw probability is divided by (1 + vig_margin),
        # so the implied probability should be lower than the raw.
        raw_prob = american_to_implied_prob(200, vig_margin=0.0)
        vig_prob = american_to_implied_prob(200, vig_margin=0.10)
        assert vig_prob < raw_prob

    def test_round_trip_approximately(self) -> None:
        # Convert a probability to American odds and back; should be close.
        original = 0.35
        odds = prob_to_american(original)
        recovered = american_to_implied_prob(odds, vig_margin=0.0)
        assert abs(recovered - original) < 0.02  # rounding in integer odds


# ---------------------------------------------------------------------------
# prob_to_american
# ---------------------------------------------------------------------------


class TestProbToAmerican:
    def test_favourite(self) -> None:
        # p = 0.75 → -300
        assert prob_to_american(0.75) == -300

    def test_underdog(self) -> None:
        # p = 0.25 → +300
        assert prob_to_american(0.25) == 300

    def test_even_money(self) -> None:
        assert prob_to_american(0.5) == -100

    def test_invalid_zero(self) -> None:
        with pytest.raises(ValueError):
            prob_to_american(0.0)

    def test_invalid_one(self) -> None:
        with pytest.raises(ValueError):
            prob_to_american(1.0)

    def test_returns_int(self) -> None:
        assert isinstance(prob_to_american(0.4), int)


# ---------------------------------------------------------------------------
# kelly
# ---------------------------------------------------------------------------


class TestKelly:
    def test_no_edge_returns_zero(self) -> None:
        # model_prob == implied_prob → no edge → stake 0
        assert kelly(0.30, 0.30) == 0.0

    def test_negative_edge_returns_zero(self) -> None:
        assert kelly(0.20, 0.35) == 0.0

    def test_positive_edge(self) -> None:
        # model_prob clearly exceeds implied_prob → positive stake
        stake = kelly(0.40, 0.25)
        assert stake > 0.0

    def test_half_kelly_applied(self) -> None:
        # Full Kelly formula: f = (b*p - q) / b
        # b = 1/implied_prob - 1
        model_p = 0.40
        implied_p = 0.25
        decimal = 1.0 / implied_p
        b = decimal - 1.0
        full_kelly = (b * model_p - (1.0 - model_p)) / b
        half_kelly = full_kelly * 0.5
        assert abs(kelly(model_p, implied_p) - half_kelly) < 1e-9

    def test_invalid_implied_prob_returns_zero(self) -> None:
        assert kelly(0.5, 0.0) == 0.0


# ---------------------------------------------------------------------------
# ev_per_dollar
# ---------------------------------------------------------------------------


class TestEvPerDollar:
    def test_zero_implied_prob_returns_zero(self) -> None:
        assert ev_per_dollar(0.5, 0.0) == 0.0

    def test_positive_ev(self) -> None:
        # model_prob = 0.5, implied_prob = 0.3 → clear positive EV
        ev = ev_per_dollar(0.5, 0.3)
        assert ev > 0.0

    def test_negative_ev(self) -> None:
        # model_prob = 0.1, implied_prob = 0.5 → negative EV
        ev = ev_per_dollar(0.1, 0.5)
        assert ev < 0.0

    def test_breakeven_approximately(self) -> None:
        # When model_prob == implied_prob, EV ≈ 0.
        p = 0.35
        decimal = 1.0 / p
        ev = p * (decimal - 1.0) - (1.0 - p)
        assert abs(ev) < 1e-6


# ---------------------------------------------------------------------------
# build_betting_board
# ---------------------------------------------------------------------------


class TestBuildBettingBoard:
    def _board(
        self,
        outcome_key: str = "win_prob",
        n_players: int = 5,
    ) -> BettingBoard:
        outcomes = tuple(
            _make_outcome(
                player_id=i,
                player_name=f"Player {i}",
                win_prob=0.05 + i * 0.03,
                top_5_prob=0.15 + i * 0.06,
                top_10_prob=0.30 + i * 0.06,
                top_20_prob=0.50 + i * 0.04,
                make_cut_prob=0.80 + i * 0.02,
            )
            for i in range(1, n_players + 1)
        )
        return build_betting_board(
            outcomes,
            tournament_id=1,
            tournament_name="Test Open",
            outcome_key=outcome_key,
        )

    def test_returns_betting_board(self) -> None:
        board = self._board()
        assert isinstance(board, BettingBoard)

    def test_lines_sorted_by_ev_descending(self) -> None:
        board = self._board()
        evs = [line.ev_per_dollar for line in board.lines]
        assert evs == sorted(evs, reverse=True)

    def test_all_players_present(self) -> None:
        board = self._board(n_players=5)
        assert len(board.lines) == 5

    def test_edge_computed_correctly(self) -> None:
        board = self._board()
        for line in board.lines:
            expected_edge = line.model_prob - line.implied_prob
            assert abs(line.edge - expected_edge) < 1e-9

    def test_kelly_zero_when_no_edge(self) -> None:
        board = self._board()
        for line in board.lines:
            if line.edge < 0:
                assert line.kelly_fraction == 0.0

    def test_positive_ev_lines_property(self) -> None:
        board = self._board()
        for line in board.positive_ev_lines:
            assert line.edge >= MIN_EDGE

    def test_skips_near_zero_probability(self) -> None:
        # A player with effectively zero probability should be dropped.
        tiny = _make_outcome(player_id=99, player_name="No-Hope", win_prob=0.0005)
        outcomes = (tiny,) + tuple(
            _make_outcome(player_id=i, player_name=f"P{i}", win_prob=0.10)
            for i in range(1, 4)
        )
        board = build_betting_board(
            outcomes,
            tournament_id=2,
            tournament_name="Skip Test",
            outcome_key="win_prob",
        )
        ids = {line.player_id for line in board.lines}
        assert 99 not in ids

    def test_american_odds_are_integers(self) -> None:
        board = self._board()
        for line in board.lines:
            assert isinstance(line.american_odds, int)

    def test_outcome_key_top5(self) -> None:
        # Switching to top_5_prob should change model_prob values.
        board_win = self._board(outcome_key="win_prob")
        board_top5 = self._board(outcome_key="top_5_prob")
        # top-5 probs are systematically higher than win probs in our fixture.
        avg_win = sum(ln.model_prob for ln in board_win.lines) / len(board_win.lines)
        avg_top5 = sum(ln.model_prob for ln in board_top5.lines) / len(board_top5.lines)
        assert avg_top5 > avg_win

    def test_tournament_metadata_preserved(self) -> None:
        board = self._board()
        assert board.tournament_id == 1
        assert board.tournament_name == "Test Open"
        assert board.outcome_key == "win_prob"

    def test_no_real_odds_marks_source_model(self) -> None:
        board = self._board()
        assert board.odds_source == "model"
        assert all(line.odds_source == "model" for line in board.lines)


class TestRealOdds:
    """The real-odds path: when a sportsbook consensus is supplied, matching
    players are priced against the de-vigged line and flagged ``datagolf``."""

    def _outcomes(self, n: int = 4) -> tuple[PlayerOutcome, ...]:
        return tuple(
            _make_outcome(
                player_id=i,
                player_name=f"Player {i}",
                win_prob=0.10 + i * 0.05,
            )
            for i in range(1, n + 1)
        )

    def test_real_odds_used_and_flagged(self) -> None:
        outcomes = self._outcomes()
        # Real American odds for two of the four players (player_id → odds).
        real = {1: 500, 2: 250}
        board = build_betting_board(
            outcomes,
            tournament_id=1,
            tournament_name="Real Open",
            outcome_key="win_prob",
            real_odds=real,
        )
        assert board.odds_source == "datagolf"
        by_id = {ln.player_id: ln for ln in board.lines}
        # Players with a real line carry the exact American odds + datagolf flag.
        assert by_id[1].odds_source == "datagolf"
        assert by_id[1].american_odds == 500
        assert by_id[2].american_odds == 250
        # Players without a real line fall back to synthetic.
        assert by_id[3].odds_source == "model"
        assert by_id[4].odds_source == "model"

    def test_win_market_devig_normalizes_to_one(self) -> None:
        # A full field whose raw implied probs overround to >1 must de-vig so the
        # fair implied probabilities sum back to ~1.0 for the win market.
        outcomes = self._outcomes(n=3)
        # +100 each → raw implied 0.5 each → sum 1.5 (a 50% overround).
        real = {1: 100, 2: 100, 3: 100}
        board = build_betting_board(
            outcomes,
            tournament_id=1,
            tournament_name="Devig Open",
            outcome_key="win_prob",
            real_odds=real,
        )
        total_implied = sum(ln.implied_prob for ln in board.lines)
        assert total_implied == pytest.approx(1.0, abs=1e-6)
