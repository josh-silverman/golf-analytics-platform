"""Why a board has no DataGolf coverage, recorded rather than inferred.

`dg_direct_count == 0` has two causes that want opposite reactions: DataGolf
genuinely has nothing for this field (a legitimate cold-start board), or the
fetch did not describe this event at all — most often because DataGolf's live
pre-tournament endpoint, which takes no event parameter, was still featuring
last week's tournament on Wednesday evening. Capture is first-write-wins, so
whichever reading gets pinned is permanent. These tests pin the distinction,
the refuse-then-retry policy built on it, and the predicate A4b must use.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from app.domain.enums import DgFetchStatus, TournamentStatus
from app.domain.models import Tournament
from app.services.board_archive import (
    BoardSnapshot,
    BoardSnapshotOutcome,
    FileBoardArchive,
    _from_dict,
    _to_json,
    snapshot_from_predictions,
)
from app.services.board_capture import CaptureOutcome, capture_pre_event_board

_START = date(2026, 8, 27)
_TODAY = date(2026, 8, 26)


class _Catalog:
    async def get_tournament(self, tournament_id: int) -> Tournament:
        return Tournament(
            id=tournament_id,
            course_id=1,
            name="TOUR Championship",
            season=2026,
            start_date=_START,
            end_date=_START,
            purse=None,
            field_strength=None,
            status=TournamentStatus.UPCOMING,
        )


class _Preds:
    """Just enough of ``TournamentPredictions`` for the capture path."""

    tournament_id = 60
    tournament_name = "TOUR Championship"
    model_name = "golf_v1"
    model_version_id = "path_a@v2"
    feature_set_hash = "deadbeef"
    model_trained_through = date(2026, 8, 1)
    as_of = _TODAY

    def __init__(self, status: DgFetchStatus, *, covered: int = 0) -> None:
        self.dg_fetch_status = status
        self.dg_direct_count = covered
        self.dg_baseline = {
            100 + i: {
                "win_prob": 0.02,
                "top_5_prob": 0.1,
                "top_10_prob": 0.2,
                "top_20_prob": 0.4,
                "make_cut_prob": 0.7,
            }
            for i in range(covered)
        }
        self.outcomes = tuple(
            BoardSnapshotOutcome(200 + i, 0.02, 0.1, 0.2, 0.4, 0.7) for i in range(3)
        )


# ---------------------------------------------------------------------------
# The refuse-then-retry policy
# ---------------------------------------------------------------------------


async def test_strict_run_refuses_a_failed_fetch_and_writes_nothing(tmp_path) -> None:
    """The 21:00 run. Nothing written is the point: first-write-wins would
    otherwise let a degraded capture lock out the retry meant to fix it."""
    archive = FileBoardArchive(tmp_path)
    outcome = await capture_pre_event_board(
        catalog=_Catalog(),  # type: ignore[arg-type]
        archive=archive,
        predictions=_Preds(DgFetchStatus.FETCH_FAILED),  # type: ignore[arg-type]
        today=_TODAY,
        allow_degraded=False,
    )
    assert outcome is CaptureOutcome.DG_FETCH_FAILED
    assert not outcome.is_healthy
    assert outcome.is_retryable  # 23:30 can still do better
    assert await archive.list_all() == []


async def test_retry_captures_the_degraded_board_with_an_honest_label(tmp_path) -> None:
    """The 23:30 run. A labelled degraded board beats no board for the week."""
    archive = FileBoardArchive(tmp_path)
    outcome = await capture_pre_event_board(
        catalog=_Catalog(),  # type: ignore[arg-type]
        archive=archive,
        predictions=_Preds(DgFetchStatus.FETCH_FAILED),  # type: ignore[arg-type]
        today=_TODAY,
        allow_degraded=True,
    )
    assert outcome is CaptureOutcome.CAPTURED
    (stored,) = await archive.list_all()
    assert stored.dg_fetch_status == "fetch_failed"
    assert stored.dg_direct_count == 0
    # And it is not silently usable as a DataGolf baseline.
    assert stored.dg_baseline_is_usable is False


async def test_a_real_cold_start_board_is_captured_even_on_the_strict_run(tmp_path) -> None:
    """`no_coverage` is not a failure. DataGolf having nothing for a field is
    a fact about the field, and refusing it would lose the board for nothing."""
    archive = FileBoardArchive(tmp_path)
    outcome = await capture_pre_event_board(
        catalog=_Catalog(),  # type: ignore[arg-type]
        archive=archive,
        predictions=_Preds(DgFetchStatus.NO_COVERAGE),  # type: ignore[arg-type]
        today=_TODAY,
        allow_degraded=False,
    )
    assert outcome is CaptureOutcome.CAPTURED
    (stored,) = await archive.list_all()
    assert stored.dg_fetch_status == "no_coverage"


async def test_the_start_guard_still_outranks_the_fetch_refusal(tmp_path) -> None:
    """An event that has begun reports that, not the DataGolf problem: the
    start guard is terminal for the week and the fetch refusal is not."""
    archive = FileBoardArchive(tmp_path)
    outcome = await capture_pre_event_board(
        catalog=_Catalog(),  # type: ignore[arg-type]
        archive=archive,
        predictions=_Preds(DgFetchStatus.FETCH_FAILED),  # type: ignore[arg-type]
        today=_START,
        allow_degraded=False,
    )
    assert outcome is CaptureOutcome.EVENT_ALREADY_STARTED
    assert not outcome.is_retryable


async def test_a_healthy_capture_records_ok_and_a_usable_baseline(tmp_path) -> None:
    archive = FileBoardArchive(tmp_path)
    outcome = await capture_pre_event_board(
        catalog=_Catalog(),  # type: ignore[arg-type]
        archive=archive,
        predictions=_Preds(DgFetchStatus.OK, covered=3),  # type: ignore[arg-type]
        today=_TODAY,
        allow_degraded=False,
    )
    assert outcome is CaptureOutcome.CAPTURED
    (stored,) = await archive.list_all()
    assert stored.dg_fetch_status == "ok"
    assert stored.dg_baseline_is_usable is True
    assert len(stored.dg_baseline or ()) == 3


# ---------------------------------------------------------------------------
# The predicate A4b must use, and storage
# ---------------------------------------------------------------------------


def _snap(**kwargs: object) -> BoardSnapshot:
    return BoardSnapshot(
        tournament_id=1,
        tournament_name="The Demo",
        tournament_start_date="2026-06-01",
        model_name="golf_v1",
        model_version_id="path_a@v2",
        feature_set_hash="deadbeef",
        model_trained_through="2026-05-01",
        as_of="2026-05-31",
        captured_at="2026-05-31T12:00:00+00:00",
        outcomes=(BoardSnapshotOutcome(10, 0.4, 0.7, 0.8, 0.9, 0.98),),
        **kwargs,  # type: ignore[arg-type]
    )


_BASELINE = (BoardSnapshotOutcome(11, 0.3, 0.5, 0.6, 0.8, 0.95),)


@pytest.mark.parametrize(
    ("status", "baseline", "usable"),
    [
        ("ok", _BASELINE, True),
        ("fetch_failed", _BASELINE, False),  # stale feed: exclude, don't count as zero
        ("no_coverage", (), False),
        ("not_attempted", None, False),
        (None, None, False),  # pre-A4a board: reason unrecoverable
        ("ok", (), False),  # claims success but pinned nothing
        ("something_newer", _BASELINE, False),  # written by a newer build
    ],
)
def test_baseline_usability(status, baseline, usable) -> None:
    assert _snap(dg_fetch_status=status, dg_baseline=baseline).dg_baseline_is_usable is usable


def test_status_round_trips_and_absence_stays_absent() -> None:
    populated = _snap(dg_fetch_status="fetch_failed", dg_baseline=())
    assert _from_dict(json.loads(_to_json(populated))) == populated

    legacy = json.loads(_to_json(_snap()))
    legacy.pop("dg_fetch_status")
    assert _from_dict(legacy).dg_fetch_status is None


def test_snapshot_from_predictions_records_the_status() -> None:
    snapshot = snapshot_from_predictions(
        _Preds(DgFetchStatus.FETCH_FAILED),
        tournament_start_date=_START,
        model_trained_through=date(2026, 8, 1),
    )
    assert snapshot.dg_fetch_status == "fetch_failed"
