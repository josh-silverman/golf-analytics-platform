"""Tests for the Monte Carlo simulation engine and service layer."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from app.simulation.engine import (
    PlayerEntry,
    simulate,
)


def _entry(
    pid: int = 1,
    name: str = "Alice",
    expected_score: float = 0.0,
) -> PlayerEntry:
    return PlayerEntry(
        player_id=pid,
        player_name=name,
        expected_score=expected_score,
        score_std=0.0,
    )


def _rng(seed: int = 42) -> np.random.Generator:
    return np.random.default_rng(seed)


# ---------------------------------------------------------------------------
# Engine basics
# ---------------------------------------------------------------------------


def test_simulate_returns_one_outcome_per_player() -> None:
    entries = [_entry(i) for i in range(10)]
    results = simulate(entries, n_iterations=100, rng=_rng())
    assert len(results) == 10


def test_simulate_empty_field_returns_empty() -> None:
    assert simulate([], n_iterations=100, rng=_rng()) == ()


def test_simulate_probabilities_are_in_range() -> None:
    entries = [_entry(i, expected_score=float(i - 5)) for i in range(20)]
    results = simulate(entries, n_iterations=500, score_std=3.0, rng=_rng())
    for o in results:
        assert 0.0 <= o.win_prob <= 1.0
        assert 0.0 <= o.top_5_prob <= 1.0
        assert 0.0 <= o.top_10_prob <= 1.0
        assert 0.0 <= o.top_20_prob <= 1.0
        assert 0.0 <= o.make_cut_prob <= 1.0


def test_probabilities_are_monotone_win_le_top5_le_top10_le_top20() -> None:
    """Core correctness: simulation produces coherent probability sets."""
    entries = [_entry(i, expected_score=float(i - 10)) for i in range(30)]
    results = simulate(entries, n_iterations=1_000, score_std=3.0, rng=_rng())
    for o in results:
        assert o.win_prob <= o.top_5_prob + 1e-9, f"win > top5 for {o.player_name}"
        assert o.top_5_prob <= o.top_10_prob + 1e-9
        assert o.top_10_prob <= o.top_20_prob + 1e-9
        assert o.top_20_prob <= o.make_cut_prob + 1e-9


def test_stronger_player_has_higher_win_probability() -> None:
    """The best player in a zero-variance simulation always wins."""
    entries = [
        PlayerEntry(0, "Elite", expected_score=-5.0, score_std=0.0),
        PlayerEntry(1, "Average", expected_score=0.0, score_std=0.0),
        PlayerEntry(2, "Weak", expected_score=3.0, score_std=0.0),
    ]
    # Zero variance → deterministic: Elite always wins
    results = simulate(entries, n_iterations=100, score_std=0.0, rng=_rng())
    by_id = {o.player_id: o for o in results}
    assert by_id[0].win_prob == pytest.approx(1.0)
    assert by_id[1].win_prob == pytest.approx(0.0)
    assert by_id[2].win_prob == pytest.approx(0.0)


def test_cut_line_limits_make_cut_count() -> None:
    """At most cut_line players should make the cut per iteration."""
    n = 40
    entries = [_entry(i, expected_score=0.0) for i in range(n)]
    cut = 10
    results = simulate(
        entries, n_iterations=500, score_std=3.0, cut_line=cut, rng=_rng()
    )
    # Expected make-cut players across the field ≈ cut_line / n_players
    total_make_cut = sum(o.make_cut_prob for o in results)
    assert abs(total_make_cut - cut) < 2.0  # within 2 of the cut line


def test_results_sorted_by_win_prob_descending() -> None:
    entries = [_entry(i, expected_score=float(i - 10)) for i in range(20)]
    results = simulate(entries, n_iterations=500, score_std=3.0, rng=_rng())
    probs = [o.win_prob for o in results]
    assert probs == sorted(probs, reverse=True)


def test_deterministic_with_same_seed() -> None:
    entries = [_entry(i, expected_score=float(i - 5)) for i in range(15)]
    r1 = simulate(entries, n_iterations=200, score_std=3.0, rng=_rng(99))
    r2 = simulate(entries, n_iterations=200, score_std=3.0, rng=_rng(99))
    for o1, o2 in zip(r1, r2, strict=True):
        assert o1.win_prob == o2.win_prob


def test_win_probs_sum_to_one() -> None:
    """Exactly one player wins every iteration."""
    entries = [_entry(i, expected_score=0.0) for i in range(50)]
    results = simulate(entries, n_iterations=1_000, score_std=3.0, rng=_rng())
    total = sum(o.win_prob for o in results)
    assert total == pytest.approx(1.0, abs=0.02)


def test_single_player_always_wins() -> None:
    results = simulate([_entry(0)], n_iterations=100, score_std=3.0, rng=_rng())
    assert len(results) == 1
    assert results[0].win_prob == pytest.approx(1.0)
    assert results[0].make_cut_prob == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# SimulationService
# ---------------------------------------------------------------------------


class _StubExtraction:
    def __init__(self, sg_total: float = 1.0) -> None:
        self.values = {"sg_total_rating": sg_total}


class _StubExtractor:
    async def extract(self, player_id: int, as_of: object) -> _StubExtraction:
        return _StubExtraction(sg_total=float(player_id) * 0.1)


class _StubPlayer:
    def __init__(self, pid: int) -> None:
        self.id = pid
        self.full_name = f"Player {pid}"


class _StubEntry:
    def __init__(self, pid: int) -> None:
        self.player_id = pid


class _StubTournament:
    def __init__(self, tid: int = 1) -> None:
        self.id = tid
        self.name = "Demo Open"


class _StubCatalog:
    def __init__(self, *, found: bool = True, n_players: int = 5) -> None:
        self._found = found
        self._n = n_players

    async def get_tournament(self, tid: int) -> _StubTournament | None:
        return _StubTournament(tid) if self._found else None

    async def get_tournament_field(self, tid: int) -> list[_StubEntry]:
        return [_StubEntry(i) for i in range(self._n)]

    async def get_player(self, pid: int) -> _StubPlayer:
        return _StubPlayer(pid)


async def test_simulation_service_returns_one_outcome_per_field_player() -> None:
    from app.simulation.service import SimulationService

    svc = SimulationService(
        catalog=_StubCatalog(n_players=8),  # type: ignore[arg-type]
        extractor=_StubExtractor(),  # type: ignore[arg-type]
    )
    result = await svc.simulate_tournament(1, as_of=date(2026, 5, 1))
    assert result is not None
    assert result.tournament_id == 1
    assert len(result.outcomes) == 8


async def test_simulation_service_returns_none_for_unknown_tournament() -> None:
    from app.simulation.service import SimulationService

    svc = SimulationService(
        catalog=_StubCatalog(found=False),  # type: ignore[arg-type]
        extractor=_StubExtractor(),  # type: ignore[arg-type]
    )
    result = await svc.simulate_tournament(999, as_of=date(2026, 5, 1))
    assert result is None


async def test_simulation_service_higher_sg_gets_higher_win_prob() -> None:
    """Better sg_total_rating → lower expected score → higher win probability."""
    from app.simulation.service import SimulationConfig, SimulationService

    cfg = SimulationConfig(n_iterations=2_000, score_std=3.0)
    svc = SimulationService(
        catalog=_StubCatalog(n_players=10),  # type: ignore[arg-type]
        extractor=_StubExtractor(),  # type: ignore[arg-type]
        config=cfg,
    )
    # Player 9 has sg_total=0.9, player 0 has sg_total=0.0.
    result = await svc.simulate_tournament(
        1, as_of=date(2026, 5, 1), rng=np.random.default_rng(7)
    )
    assert result is not None
    by_id = {o.player_id: o for o in result.outcomes}
    assert by_id[9].win_prob > by_id[0].win_prob
