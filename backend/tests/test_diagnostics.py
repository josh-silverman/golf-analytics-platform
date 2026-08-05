"""Tests for the read-only backtest diagnostics module.

``run_diagnostics`` claims to mirror ``run_backtest`` exactly (same split,
same model, same coherence + field-normalization step) — this exercises that
claim end to end rather than only through the shared helper both call into.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pytest

from app.domain.enums import EntryStatus, TournamentStatus
from app.domain.models import Page, Player, Tournament, TournamentEntry
from app.features.feature_sets import v1_baseline
from app.ml.diagnostics import run_diagnostics
from app.ml.trainer import GBDTTrainer, TrainerConfig

_SMALL_DATA_TRAINER = GBDTTrainer(TrainerConfig(max_depth=2, min_samples_leaf=5))


def _player(pid: int) -> Player:
    return Player(
        id=pid,
        dg_id=None,
        full_name=f"Player {pid}",
        country="USA",
        dob=None,
        turned_pro=2020,
    )


def _tournament(tid: int, start: date) -> Tournament:
    return Tournament(
        id=tid,
        course_id=1,
        name=f"Event {tid}",
        season=start.year,
        start_date=start,
        end_date=start + timedelta(days=3),
        purse=1_000_000,
        field_strength=None,
        status=TournamentStatus.COMPLETED,
    )


def _field(tid: int, n_players: int) -> list[TournamentEntry]:
    """Every player made the cut, so every player is scored in every event —
    keeps the field-sum assertion below simple (no worst-placement branch).
    """
    entries: list[TournamentEntry] = []
    ordered = sorted(range(1, n_players + 1), reverse=True)
    for position, pid in enumerate(ordered, start=1):
        entries.append(
            TournamentEntry(
                id=tid * 1000 + pid,
                tournament_id=tid,
                player_id=pid,
                status=EntryStatus.MADE_CUT,
                final_position=position,
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
        self,
        *,
        season=None,
        status=None,
        cursor=None,
        limit=200,
    ) -> Page[Tournament]:
        items = [t for t in self._tournaments if status is None or t.status == status]
        return Page(items=items, next_cursor=None, total=len(items))

    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]:
        return list(self._fields.get(tournament_id, []))

    async def get_player(self, player_id: int) -> Player | None:
        return self._players.get(player_id)


@dataclass
class _Extraction:
    values: dict[str, float]


class _SkillExtractor:
    """Deterministic skill feature keyed on player id, matching test_backtest.py."""

    def __init__(self) -> None:
        self.feature_set = v1_baseline()

    async def extract_field(
        self, player_ids: list[int], as_of: date, *, event: object | None = None
    ) -> dict[int, _Extraction]:
        return {pid: _Extraction(values={"skill": float(pid)}) for pid in dict.fromkeys(player_ids)}


async def test_run_diagnostics_probabilities_are_field_normalized() -> None:
    """Each event's rows must sum to the field's theoretical total (one
    winner, etc.) — the same invariant run_backtest scores. Before the
    normalize_field fix, diagnostics.py applied coherent_outcomes per player
    but never normalized across the field, so this would fail.
    """
    starts = [date(2026, m, 1) for m in range(1, 9)]
    tournaments = [_tournament(i + 1, s) for i, s in enumerate(starts)]
    catalog = _StubCatalog(tournaments, n_players=20)

    result = await run_diagnostics(
        catalog=catalog,  # type: ignore[arg-type]
        extractor=_SkillExtractor(),  # type: ignore[arg-type]
        base_trainer=_SMALL_DATA_TRAINER,
        test_events=3,
        holdout_fraction=0.25,
    )

    assert len(result.rows) > 0

    by_tournament: dict[int, list[float]] = {}
    for row in result.rows:
        by_tournament.setdefault(row.tournament_id, []).append(row.probs["win_prob"])

    for tid, win_probs in by_tournament.items():
        assert sum(win_probs) == pytest.approx(1.0, abs=1e-6), (
            f"tournament {tid}: win probabilities summed to {sum(win_probs)}, expected 1.0"
        )
