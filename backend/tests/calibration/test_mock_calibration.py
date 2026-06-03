"""Statistical validation of the mock data generator.

These tests verify the generated dataset matches the calibration targets
from doc 02 §6. They run against the deterministic seeded output, so a
failure here means the generator drifted out of distribution — not a
flaky test.

Generation is expensive (a few hundred ms) so we cache one dataset across
the whole module via a session fixture.
"""

from __future__ import annotations

from itertools import groupby

import numpy as np
import pytest

from app.domain.enums import EntryStatus, TournamentStatus
from app.providers.mock.generator import MockDataset, generate

# Generation is expensive (~50s per dataset). Mark the whole module slow so
# the fast PR lane skips it; a separate workflow / nightly job runs `-m slow`.
pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def dataset() -> MockDataset:
    return generate(seed=42)


# --- Determinism ------------------------------------------------------------


def test_generation_is_deterministic_under_same_seed() -> None:
    a = generate(seed=123)
    b = generate(seed=123)
    assert len(a.rounds) == len(b.rounds)
    # Sample a handful of fields; if the seed is honored they're bit-identical
    assert [p.full_name for p in a.players[:10]] == [p.full_name for p in b.players[:10]]
    assert [r.sg_total for r in a.rounds[:50]] == [r.sg_total for r in b.rounds[:50]]


def test_different_seeds_produce_different_data() -> None:
    a = generate(seed=1)
    b = generate(seed=2)
    assert [p.full_name for p in a.players[:5]] != [p.full_name for p in b.players[:5]]


# --- Player population shape ------------------------------------------------


def test_player_count_matches_target(dataset: MockDataset) -> None:
    assert len(dataset.players) == 250


def test_courses_count_matches_target(dataset: MockDataset) -> None:
    assert len(dataset.courses) == 50


def test_tournaments_span_five_seasons(dataset: MockDataset) -> None:
    seasons = {t.season for t in dataset.tournaments}
    assert seasons == {2022, 2023, 2024, 2025, 2026}


# --- Score distribution -----------------------------------------------------


def test_mean_round_score_in_target_range(dataset: MockDataset) -> None:
    scores = np.array([r.score for r in dataset.rounds])
    mean = float(scores.mean())
    assert 69.5 <= mean <= 72.5, (
        f"mean round score {mean:.2f} outside target ~70.5–71.5 (allowing 1σ slack)"
    )


def test_round_score_std_in_target_range(dataset: MockDataset) -> None:
    scores = np.array([r.score for r in dataset.rounds])
    std = float(scores.std())
    assert 2.0 <= std <= 3.5, (
        f"round score std {std:.2f} outside target ~2.5–3.0 (allowing 1σ slack)"
    )


# --- SG distribution --------------------------------------------------------


def test_sg_components_sum_to_total_per_round(dataset: MockDataset) -> None:
    """Invariant the contract tests assert: sg_t2g = ott + app + arg, and
    sg_total = sg_t2g + sg_putt. Mock generator must honor this.
    """
    for r in dataset.rounds[:200]:
        assert abs((r.sg_ott + r.sg_app + r.sg_arg) - r.sg_t2g) < 0.01
        assert abs((r.sg_t2g + r.sg_putt) - r.sg_total) < 0.01


def test_top_player_skill_near_plus_two(dataset: MockDataset) -> None:
    """Top player's mean SG:Total per round should be roughly +2.0 vs field
    average. We aggregate per-player and check the max.
    """
    player_sg: dict[int, list[float]] = {}
    for entry in dataset.entries:
        for r in dataset.rounds:
            if r.entry_id == entry.id:
                player_sg.setdefault(entry.player_id, []).append(r.sg_total)
    means = [np.mean(v) for v in player_sg.values() if len(v) >= 20]
    top_mean = max(means)
    # With ~250 sampled skills the top z-score is ~2.7σ and skill_total_std≈1.0,
    # so top ranges roughly +1.5 to +3.5 across seeds. Doc 02 §6 target is +2.0.
    assert 1.2 <= top_mean <= 3.5, f"top player SG/round mean = {top_mean:.2f}, expected ~+2.0"


def test_long_game_sg_components_are_positively_correlated(
    dataset: MockDataset,
) -> None:
    sg_ott = np.array([r.sg_ott for r in dataset.rounds])
    sg_app = np.array([r.sg_app for r in dataset.rounds])
    sg_putt = np.array([r.sg_putt for r in dataset.rounds])
    corr_ott_app = float(np.corrcoef(sg_ott, sg_app)[0, 1])
    corr_ott_putt = float(np.corrcoef(sg_ott, sg_putt)[0, 1])
    assert 0.10 <= corr_ott_app <= 0.45, f"sg_ott/sg_app corr = {corr_ott_app:.2f}, target ~0.3"
    assert abs(corr_ott_putt) <= 0.15, f"sg_ott/sg_putt corr = {corr_ott_putt:.2f}, target ~0.0"


# --- Round-to-round correlation within a tournament -------------------------


def test_round_to_round_correlation_within_a_tournament(
    dataset: MockDataset,
) -> None:
    """A player's R1 SG and R2 SG should be correlated 0.2–0.3 (doc 02 §6)."""
    by_entry = sorted(dataset.rounds, key=lambda r: (r.entry_id, r.round_number))
    r1_vals: list[float] = []
    r2_vals: list[float] = []
    for _, group in groupby(by_entry, key=lambda r: r.entry_id):
        rounds_list = list(group)
        if len(rounds_list) >= 2:
            r1_vals.append(rounds_list[0].sg_total)
            r2_vals.append(rounds_list[1].sg_total)
    corr = float(np.corrcoef(np.array(r1_vals), np.array(r2_vals))[0, 1])
    assert 0.15 <= corr <= 0.40, f"round-to-round SG corr = {corr:.2f}, target ~0.25"


# --- Cut behaviour ----------------------------------------------------------


def test_completed_tournaments_make_cut_share_near_half(
    dataset: MockDataset,
) -> None:
    completed = [t for t in dataset.tournaments if t.status == TournamentStatus.COMPLETED]
    assert completed, "expected some completed tournaments"
    # Pick a random sample to keep the test fast
    sample = completed[:10]
    sample_ids = {t.id for t in sample}
    counts_total = 0
    counts_made = 0
    for e in dataset.entries:
        if e.tournament_id not in sample_ids:
            continue
        counts_total += 1
        if e.status == EntryStatus.MADE_CUT:
            counts_made += 1
    share = counts_made / counts_total
    assert 0.40 <= share <= 0.60, f"make-cut share {share:.2f} outside target ~0.50"


def test_made_cut_entries_have_four_rounds(dataset: MockDataset) -> None:
    rounds_by_entry: dict[int, int] = {}
    for r in dataset.rounds:
        rounds_by_entry[r.entry_id] = rounds_by_entry.get(r.entry_id, 0) + 1
    made_cut_entries = [e for e in dataset.entries if e.status == EntryStatus.MADE_CUT]
    # Sample to keep the test fast
    sample_size = 50
    for e in made_cut_entries[:sample_size]:
        assert rounds_by_entry.get(e.id, 0) == 4, (
            f"made-cut entry {e.id} has {rounds_by_entry.get(e.id, 0)} rounds, expected 4"
        )


def test_missed_cut_entries_have_two_rounds(dataset: MockDataset) -> None:
    rounds_by_entry: dict[int, int] = {}
    for r in dataset.rounds:
        rounds_by_entry[r.entry_id] = rounds_by_entry.get(r.entry_id, 0) + 1
    missed_cut = [e for e in dataset.entries if e.status == EntryStatus.MISSED_CUT]
    sample_size = 50
    for e in missed_cut[:sample_size]:
        assert rounds_by_entry.get(e.id, 0) == 2, (
            f"missed-cut entry {e.id} has {rounds_by_entry.get(e.id, 0)} rounds, expected 2"
        )


# --- Field shape ------------------------------------------------------------


def test_field_size_is_correct(dataset: MockDataset) -> None:
    by_t: dict[int, int] = {}
    for e in dataset.entries:
        by_t[e.tournament_id] = by_t.get(e.tournament_id, 0) + 1
    sizes = list(by_t.values())
    assert all(s == 156 for s in sizes), f"expected all field sizes 156, got distinct: {set(sizes)}"


# --- Betting lines ----------------------------------------------------------


def test_betting_lines_have_plausible_implied_probs(dataset: MockDataset) -> None:
    assert dataset.betting_lines, "expected some betting lines"
    probs = [bl.implied_prob for bl in dataset.betting_lines]
    assert min(probs) > 0.0 and max(probs) < 1.0
    # Decimal odds are inverse of (prob / (1 - vig)) — sanity check
    for bl in dataset.betting_lines[:200]:
        assert bl.decimal_odds > 1.0
