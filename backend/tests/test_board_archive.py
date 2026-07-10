"""Tests for the forward out-of-sample prediction-board archive + grader."""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.enums import EntryStatus, TournamentStatus
from app.domain.models import Tournament, TournamentEntry
from app.services.board_archive import (
    BoardArchive,
    BoardSnapshot,
    BoardSnapshotOutcome,
)
from app.services.forward_track_record import compute_forward_track_record


def _snapshot(
    *,
    tournament_id: int = 1,
    version: str = "path_a@v2",
    trained_through: str | None = "2026-05-01",
    start_date: str = "2026-06-01",
    outcomes: tuple[BoardSnapshotOutcome, ...] = (),
) -> BoardSnapshot:
    return BoardSnapshot(
        tournament_id=tournament_id,
        tournament_name="The Demo",
        tournament_start_date=start_date,
        model_name="golf_v1",
        model_version_id=version,
        feature_set_hash="deadbeef",
        model_trained_through=trained_through,
        as_of="2026-05-31",
        captured_at="2026-05-31T12:00:00+00:00",
        outcomes=outcomes,
    )


def test_persist_is_immutable_first_capture(tmp_path) -> None:
    archive = BoardArchive(tmp_path)
    assert archive.persist(_snapshot()) is True
    assert archive.has(1, "path_a@v2")
    # A second capture for the same (tournament, version) must NOT overwrite.
    second = _snapshot(start_date="2099-01-01")
    assert archive.persist(second) is False
    loaded = archive.list_all()
    assert len(loaded) == 1
    assert loaded[0].tournament_start_date == "2026-06-01"  # the first capture


def test_roundtrip_preserves_outcomes(tmp_path) -> None:
    archive = BoardArchive(tmp_path)
    snap = _snapshot(
        outcomes=(
            BoardSnapshotOutcome(10, 0.1, 0.2, 0.3, 0.4, 0.9),
            BoardSnapshotOutcome(11, 0.02, 0.1, 0.2, 0.3, 0.7),
        )
    )
    archive.persist(snap)
    (loaded,) = archive.list_all()
    assert len(loaded.outcomes) == 2
    assert loaded.outcomes[0].player_id == 10
    assert loaded.outcomes[0].make_cut_prob == pytest.approx(0.9)


def test_is_out_of_sample_requires_trained_before_event() -> None:
    start = date(2026, 6, 1)
    assert _snapshot(trained_through="2026-05-31").is_out_of_sample(start) is True
    assert _snapshot(trained_through="2026-06-01").is_out_of_sample(start) is False  # not strict
    assert _snapshot(trained_through="2026-07-01").is_out_of_sample(start) is False
    assert _snapshot(trained_through=None).is_out_of_sample(start) is False  # uncertifiable


class _GradeCatalog:
    """Catalog stub for grading: one completed tournament + graded field."""

    def __init__(self, *, start_date: date, status: TournamentStatus) -> None:
        self._t = Tournament(
            id=1, course_id=1, name="The Demo", season=2026,
            start_date=start_date, end_date=start_date, purse=None,
            field_strength=None, status=status,
        )
        # Player 10 won (pos 1), 11 made cut (pos 30), 12 missed cut.
        self._field = [
            TournamentEntry(id=1, tournament_id=1, player_id=10,
                            status=EntryStatus.MADE_CUT, final_position=1,
                            final_score_to_par=None, official_money_cents=None),
            TournamentEntry(id=2, tournament_id=1, player_id=11,
                            status=EntryStatus.MADE_CUT, final_position=30,
                            final_score_to_par=None, official_money_cents=None),
            TournamentEntry(id=3, tournament_id=1, player_id=12,
                            status=EntryStatus.MISSED_CUT, final_position=None,
                            final_score_to_par=None, official_money_cents=None),
        ]

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        return self._t if tournament_id == 1 else None

    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]:
        return list(self._field) if tournament_id == 1 else []


async def test_forward_grader_skips_in_sample_boards(tmp_path) -> None:
    """A board whose model trained after the event start is excluded."""
    archive = BoardArchive(tmp_path)
    archive.persist(_snapshot(trained_through="2026-07-01"))  # trained AFTER start
    catalog = _GradeCatalog(start_date=date(2026, 6, 1), status=TournamentStatus.COMPLETED)
    result = await compute_forward_track_record(archive=archive, catalog=catalog)  # type: ignore[arg-type]
    assert result is None  # nothing qualified as out-of-sample


async def test_forward_grader_grades_out_of_sample_board(tmp_path) -> None:
    archive = BoardArchive(tmp_path)
    archive.persist(_snapshot(
        trained_through="2026-05-01",  # strictly before the 06-01 start → OOS
        outcomes=(
            BoardSnapshotOutcome(10, 0.4, 0.7, 0.8, 0.9, 0.98),   # winner, high
            BoardSnapshotOutcome(11, 0.02, 0.1, 0.3, 0.6, 0.85),  # made cut
            BoardSnapshotOutcome(12, 0.01, 0.05, 0.1, 0.2, 0.40),  # missed cut
        ),
    ))
    catalog = _GradeCatalog(start_date=date(2026, 6, 1), status=TournamentStatus.COMPLETED)
    result = await compute_forward_track_record(archive=archive, catalog=catalog)  # type: ignore[arg-type]
    assert result is not None
    assert result.events == 1
    assert result.players_graded == 3
    assert result.events_to_meaningful > 0  # one event is far from meaningful
    mc = next(m for m in result.markets if m.market == "make_cut_prob")
    assert mc.n == 3
    assert 0.0 <= mc.base_rate <= 1.0


async def test_forward_grader_ignores_incomplete_events(tmp_path) -> None:
    archive = BoardArchive(tmp_path)
    archive.persist(_snapshot(trained_through="2026-05-01"))
    catalog = _GradeCatalog(start_date=date(2026, 6, 1), status=TournamentStatus.UPCOMING)
    result = await compute_forward_track_record(archive=archive, catalog=catalog)  # type: ignore[arg-type]
    assert result is None
