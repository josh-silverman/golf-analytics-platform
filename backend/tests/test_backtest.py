"""Tests for the rolling-origin backtest harness."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pytest

from app.domain.enums import EntryStatus, TournamentStatus
from app.domain.models import Page, Player, Tournament, TournamentEntry
from app.features.feature_sets import v1_baseline
from app.ml.backtest import (
    BacktestReport,
    _brier,
    _ece,
    _log_loss,
    _rankdata,
    _spearman,
    run_backtest,
)
from app.ml.trainer import GBDTTrainer, TrainerConfig

# Trainer sized for the tiny synthetic fixtures in this module: the production
# default (min_samples_leaf=80) cannot split a few-hundred-row toy dataset, so
# these harness tests use a small-data leaf minimum (mirrors _SMALL_DATA_CONFIG
# in test_trainer/test_calibration). Unrelated to the production config.
_SMALL_DATA_TRAINER = GBDTTrainer(TrainerConfig(max_depth=2, min_samples_leaf=5))

# ---------------------------------------------------------------------------
# Scoring primitives
# ---------------------------------------------------------------------------


def test_rankdata_average_ties() -> None:
    # Values 10, 10, 20 → the two 10s share ranks 1 and 2 → both 1.5; 20 → 3.
    ranks = _rankdata(np.array([10.0, 10.0, 20.0]))
    assert list(ranks) == [1.5, 1.5, 3.0]


def test_rankdata_strict_order() -> None:
    ranks = _rankdata(np.array([3.0, 1.0, 2.0]))
    assert list(ranks) == [3.0, 1.0, 2.0]


def test_spearman_perfect_positive() -> None:
    a = np.array([1.0, 2.0, 3.0, 4.0])
    b = np.array([10.0, 20.0, 30.0, 40.0])
    assert _spearman(a, b) == pytest.approx(1.0)


def test_spearman_perfect_negative() -> None:
    a = np.array([1.0, 2.0, 3.0, 4.0])
    b = np.array([40.0, 30.0, 20.0, 10.0])
    assert _spearman(a, b) == pytest.approx(-1.0)


def test_spearman_no_variance_is_zero() -> None:
    # All-equal input has no ordering information → neutral 0.0, not NaN.
    a = np.array([5.0, 5.0, 5.0])
    b = np.array([1.0, 2.0, 3.0])
    assert _spearman(a, b) == 0.0


def test_brier_perfect_and_worst() -> None:
    y = np.array([1.0, 0.0])
    assert _brier(y, np.array([1.0, 0.0])) == pytest.approx(0.0)
    assert _brier(y, np.array([0.0, 1.0])) == pytest.approx(1.0)


def test_log_loss_clips_to_finite() -> None:
    # A confident miss (predict 0 for a positive) must stay finite, not inf.
    loss = _log_loss(np.array([1.0]), np.array([0.0]))
    assert np.isfinite(loss)
    assert loss > 30.0  # -log(eps) is large but bounded


def test_ece_perfectly_calibrated_is_zero() -> None:
    # Predictions that exactly match observed frequency in each bin → ECE 0.
    y = np.array([0.0, 0.0, 1.0, 1.0])
    p = np.array([0.0, 0.0, 1.0, 1.0])
    assert _ece(y, p) == pytest.approx(0.0)


def test_ece_detects_miscalibration() -> None:
    # Always predict 0.5 but everything is a positive → gap of 0.5.
    y = np.array([1.0, 1.0, 1.0, 1.0])
    p = np.array([0.5, 0.5, 0.5, 0.5])
    assert _ece(y, p) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# End-to-end run_backtest on a small synthetic catalog
# ---------------------------------------------------------------------------


def _player(pid: int) -> Player:
    return Player(
        id=pid, dg_id=None, full_name=f"Player {pid}",
        country="USA", dob=None, turned_pro=2020,
    )


def _tournament(tid: int, start: date) -> Tournament:
    return Tournament(
        id=tid, course_id=1, name=f"Event {tid}", season=start.year,
        start_date=start, end_date=start + timedelta(days=3),
        purse=1_000_000, field_strength=None,
        status=TournamentStatus.COMPLETED,
    )


def _field(tid: int, n_players: int) -> list[TournamentEntry]:
    """Build a field where higher player id ⇒ better finish (pid n_players wins).

    Players with positions > 20 are 'missed cut' so the harness exercises both
    branches. Gives the model a learnable skill signal keyed on player id.
    """
    entries: list[TournamentEntry] = []
    # Best finishers get the lowest positions; rank by descending pid.
    ordered = sorted(range(1, n_players + 1), reverse=True)
    for position, pid in enumerate(ordered, start=1):
        made_cut = position <= 20
        entries.append(
            TournamentEntry(
                id=tid * 1000 + pid,
                tournament_id=tid,
                player_id=pid,
                status=EntryStatus.MADE_CUT if made_cut else EntryStatus.MISSED_CUT,
                final_position=position if made_cut else None,
                final_score_to_par=None,
                official_money_cents=None,
            )
        )
    return entries


class _StubCatalog:
    def __init__(self, tournaments: list[Tournament], n_players: int) -> None:
        self._tournaments = tournaments
        self._fields = {t.id: _field(t.id, n_players) for t in tournaments}
        self._players = {pid: _player(pid) for pid in range(1, n_players + 1)}

    async def list_tournaments(
        self, *, season=None, status=None, cursor=None, limit=200,
    ) -> Page[Tournament]:
        items = [
            t for t in self._tournaments
            if status is None or t.status == status
        ]
        return Page(items=items, next_cursor=None, total=len(items))

    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]:
        return list(self._fields.get(tournament_id, []))

    async def get_player(self, player_id: int) -> Player | None:
        return self._players.get(player_id)


@dataclass
class _Extraction:
    values: dict[str, float]


class _SkillExtractor:
    """Returns a deterministic skill feature keyed on player id.

    Higher player id ⇒ higher skill, matching the finish order in ``_field``,
    so a competent model should learn to rank high-id players near the top.
    """

    def __init__(self) -> None:
        self.feature_set = v1_baseline()

    async def extract(self, player_id: int, as_of: date) -> _Extraction:
        return _Extraction(values={"skill": float(player_id)})

    async def extract_field(
        self, player_ids: list[int], as_of: date
    ) -> dict[int, _Extraction]:
        return {
            pid: await self.extract(pid, as_of)
            for pid in dict.fromkeys(player_ids)
        }


async def test_run_backtest_report_shape_and_leakage() -> None:
    # 6 completed events, monthly; test on the most recent 2.
    starts = [date(2026, m, 1) for m in range(1, 7)]
    tournaments = [_tournament(i + 1, s) for i, s in enumerate(starts)]
    catalog = _StubCatalog(tournaments, n_players=30)

    report = await run_backtest(
        catalog=catalog,  # type: ignore[arg-type]
        extractor=_SkillExtractor(),  # type: ignore[arg-type]
        test_events=2,
        holdout_fraction=0.25,
    )

    assert isinstance(report, BacktestReport)
    # Leakage discipline: training cutoff is strictly before the first test event.
    assert report.train_through < tournaments[-2].start_date
    assert report.n_test_events == 2
    assert len(report.events) == 2
    # Every market should be scored.
    assert {o.outcome_key for o in report.outcomes} == {
        "win_prob", "top_5_prob", "top_10_prob", "top_20_prob", "make_cut_prob",
    }
    # Metrics live in valid ranges.
    for o in report.outcomes:
        assert 0.0 <= o.brier <= 1.0
        assert o.log_loss >= 0.0
        assert 0.0 <= o.ece <= 1.0
    r = report.ranking
    assert -1.0 <= r.spearman_winprob_vs_finish <= 1.0
    assert 0.0 <= r.winner_in_top5_rate <= 1.0


async def test_run_backtest_learns_a_strong_skill_signal() -> None:
    """With finish perfectly determined by the skill feature, the model should
    order players well — positive Spearman and the winner near the top."""
    starts = [date(2026, m, 1) for m in range(1, 9)]
    tournaments = [_tournament(i + 1, s) for i, s in enumerate(starts)]
    catalog = _StubCatalog(tournaments, n_players=40)

    report = await run_backtest(
        catalog=catalog,  # type: ignore[arg-type]
        extractor=_SkillExtractor(),  # type: ignore[arg-type]
        base_trainer=_SMALL_DATA_TRAINER,
        test_events=3,
        holdout_fraction=0.25,
    )

    # The signal is deterministic, so ordering should be clearly positive.
    assert report.ranking.spearman_winprob_vs_finish > 0.3
    # Winners should land in the top half of a 40-player field on average.
    assert report.ranking.mean_winner_predicted_rank < 20


async def test_run_backtest_requires_enough_events() -> None:
    tournaments = [_tournament(1, date(2026, 1, 1)), _tournament(2, date(2026, 2, 1))]
    catalog = _StubCatalog(tournaments, n_players=10)
    with pytest.raises(ValueError, match="more than"):
        await run_backtest(
            catalog=catalog,  # type: ignore[arg-type]
            extractor=_SkillExtractor(),  # type: ignore[arg-type]
            test_events=2,
        )
