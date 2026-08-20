"""Tests for the shared pre-event capture guard (B1).

The property that matters: a board is never pinned for an event that has
already started. Capture is first-write-wins, so a contaminated board
written after tee-off is permanent and silently poisons that event's
forward record. Both the "play has begun" signals are exercised
independently, because each covers a failure the other misses: a provider
whose status is stale, and a provider that flipped status correctly.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.domain.enums import TournamentStatus
from app.domain.models import Tournament
from app.services.board_archive import FileBoardArchive
from app.services.board_capture import CaptureOutcome, capture_pre_event_board

_START = date(2026, 6, 4)  # a Thursday


def _tournament(status: TournamentStatus = TournamentStatus.UPCOMING) -> Tournament:
    return Tournament(
        id=1,
        course_id=1,
        name="The Demo",
        season=2026,
        start_date=_START,
        end_date=_START,
        purse=None,
        field_strength=None,
        status=status,
    )


class _Catalog:
    def __init__(self, tournament: Tournament | None) -> None:
        self._t = tournament

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        return self._t


def _preds(*, outcomes: int = 2, trained_through: date | None = date(2026, 5, 1)):  # noqa: ANN202
    return SimpleNamespace(
        tournament_id=1,
        tournament_name="The Demo",
        as_of=_START,
        model_name="golf_v1",
        model_version_id="path_a@v2",
        feature_set_hash="deadbeef",
        model_trained_through=trained_through,
        outcomes=[
            SimpleNamespace(
                player_id=10 + i,
                win_prob=0.1,
                top_5_prob=0.2,
                top_10_prob=0.3,
                top_20_prob=0.4,
                make_cut_prob=0.9,
            )
            for i in range(outcomes)
        ],
        dg_direct_count=outcomes,
    )


async def _capture(tmp_path, *, today: date, status=TournamentStatus.UPCOMING, **kw):  # noqa: ANN202
    archive = FileBoardArchive(tmp_path)
    outcome = await capture_pre_event_board(
        catalog=_Catalog(_tournament(status)),  # type: ignore[arg-type]
        archive=archive,
        predictions=_preds(**kw),
        today=today,
    )
    return outcome, archive


async def test_captures_the_day_before_the_event(tmp_path) -> None:
    outcome, archive = await _capture(tmp_path, today=date(2026, 6, 3))
    assert outcome is CaptureOutcome.CAPTURED
    assert outcome.is_healthy
    assert len(await archive.list_all()) == 1


async def test_refuses_on_the_start_day_even_while_status_says_upcoming(tmp_path) -> None:
    """The calendar backstop.

    Tee times span time zones, so no hour on the start day is universally
    pre-event; a provider that has not yet flipped status must not be able to
    authorise a same-day capture.
    """
    outcome, archive = await _capture(tmp_path, today=_START, status=TournamentStatus.UPCOMING)
    assert outcome is CaptureOutcome.EVENT_ALREADY_STARTED
    assert not outcome.is_healthy
    assert await archive.list_all() == []


async def test_refuses_once_the_provider_reports_play_under_way(tmp_path) -> None:
    """The status signal, tested on a day the calendar alone would allow."""
    outcome, archive = await _capture(
        tmp_path, today=date(2026, 6, 3), status=TournamentStatus.IN_PROGRESS
    )
    assert outcome is CaptureOutcome.EVENT_ALREADY_STARTED
    assert await archive.list_all() == []


async def test_refuses_after_the_event_finished(tmp_path) -> None:
    outcome, archive = await _capture(
        tmp_path, today=date(2026, 6, 10), status=TournamentStatus.COMPLETED
    )
    assert outcome is CaptureOutcome.EVENT_ALREADY_STARTED
    assert await archive.list_all() == []


async def test_second_capture_is_an_idempotent_no_op(tmp_path) -> None:
    archive = FileBoardArchive(tmp_path)
    catalog = _Catalog(_tournament())
    kwargs = {"catalog": catalog, "archive": archive, "today": date(2026, 6, 3)}
    first = await capture_pre_event_board(predictions=_preds(), **kwargs)  # type: ignore[arg-type]
    second = await capture_pre_event_board(predictions=_preds(), **kwargs)  # type: ignore[arg-type]
    assert first is CaptureOutcome.CAPTURED
    assert second is CaptureOutcome.ALREADY_CAPTURED
    assert second.is_healthy  # the normal retry case, not a failure
    assert len(await archive.list_all()) == 1


async def test_already_captured_wins_over_the_start_guard(tmp_path) -> None:
    """A retry after tee-off reports the no-op, not a refusal.

    Only a genuinely missing board should raise the alarm; an event captured
    on time and re-checked later is healthy.
    """
    archive = FileBoardArchive(tmp_path)
    catalog = _Catalog(_tournament())
    await capture_pre_event_board(
        catalog=catalog,  # type: ignore[arg-type]
        archive=archive,
        predictions=_preds(),
        today=date(2026, 6, 3),
    )
    late = await capture_pre_event_board(
        catalog=_Catalog(_tournament(TournamentStatus.IN_PROGRESS)),  # type: ignore[arg-type]
        archive=archive,
        predictions=_preds(),
        today=_START,
    )
    assert late is CaptureOutcome.ALREADY_CAPTURED
    assert late.is_healthy


async def test_never_pins_an_empty_board(tmp_path) -> None:
    outcome, archive = await _capture(tmp_path, today=date(2026, 6, 3), outcomes=0)
    assert outcome is CaptureOutcome.NO_FIELD
    assert not outcome.is_healthy  # a field that never published is worth flagging
    assert await archive.list_all() == []


async def test_refuses_without_a_certifiable_training_cutoff(tmp_path) -> None:
    outcome, archive = await _capture(tmp_path, today=date(2026, 6, 3), trained_through=None)
    assert outcome is CaptureOutcome.NO_TRAINING_CUTOFF
    assert await archive.list_all() == []


async def test_missing_tournament_is_reported_not_captured(tmp_path) -> None:
    archive = FileBoardArchive(tmp_path)
    outcome = await capture_pre_event_board(
        catalog=_Catalog(None),  # type: ignore[arg-type]
        archive=archive,
        predictions=_preds(),
        today=date(2026, 6, 3),
    )
    assert outcome is CaptureOutcome.TOURNAMENT_NOT_FOUND
    assert await archive.list_all() == []
