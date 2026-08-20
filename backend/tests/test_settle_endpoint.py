"""Endpoint tests for the scheduled settle-and-grade run (B2).

Pins the admin gate, idempotency (a second run pins nothing), and the fact
that a newly completed event is reported as newly settled exactly once. The
settlement machinery itself is tested in ``test_settlement_archive.py`` and
the grading semantics in ``test_board_archive.py``.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

import app.api.v1.analytics as analytics_module
from app.api.v1.deps import (
    get_board_archive,
    get_catalog_service,
    get_settlement_archive,
)
from app.domain.enums import EntryStatus, TournamentStatus
from app.domain.models import Tournament, TournamentEntry
from app.services.board_archive import (
    BoardSnapshot,
    BoardSnapshotOutcome,
    FileBoardArchive,
)
from app.services.settlement_archive import FileSettlementArchive

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

_URL = "/api/v1/analytics/track-record/settle"
_START = date(2026, 6, 1)


def _board(tournament_id: int) -> BoardSnapshot:
    return BoardSnapshot(
        tournament_id=tournament_id,
        tournament_name=f"Event {tournament_id}",
        tournament_start_date=_START.isoformat(),
        model_name="golf_v1",
        model_version_id="path_a@v2",
        feature_set_hash="deadbeef",
        model_trained_through="2026-05-01",
        as_of="2026-05-31",
        captured_at="2026-05-31T12:00:00+00:00",
        outcomes=(
            BoardSnapshotOutcome(10, 0.4, 0.7, 0.8, 0.9, 0.98),
            BoardSnapshotOutcome(11, 0.02, 0.1, 0.3, 0.6, 0.85),
            BoardSnapshotOutcome(12, 0.01, 0.05, 0.1, 0.2, 0.40),
        ),
        dg_direct_count=3,
    )


class _Catalog:
    """Serves a set of tournaments; ``completed`` decides which have finished."""

    source_name = "stub-provider"

    def __init__(self, ids: set[int], completed: set[int]) -> None:
        self._ids = ids
        self._completed = completed

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        if tournament_id not in self._ids:
            return None
        status = (
            TournamentStatus.COMPLETED
            if tournament_id in self._completed
            else TournamentStatus.IN_PROGRESS
        )
        return Tournament(
            id=tournament_id,
            course_id=1,
            name=f"Event {tournament_id}",
            season=2026,
            start_date=_START,
            end_date=_START,
            purse=None,
            field_strength=None,
            status=status,
        )

    async def get_tournament_field(self, tournament_id: int) -> list[TournamentEntry]:
        rows = [
            (10, EntryStatus.MADE_CUT, 1),
            (11, EntryStatus.MADE_CUT, 30),
            (12, EntryStatus.MISSED_CUT, None),
        ]
        return [
            TournamentEntry(
                id=i,
                tournament_id=tournament_id,
                player_id=pid,
                status=st,
                final_position=pos,
                final_score_to_par=None,
                official_money_cents=None,
            )
            for i, (pid, st, pos) in enumerate(rows)
        ]


@pytest.fixture
def settle_ctx(
    app: FastAPI, monkeypatch, tmp_path
) -> Iterator[tuple[TestClient, object, _Catalog]]:
    boards = FileBoardArchive(tmp_path / "boards")
    settlements = FileSettlementArchive(tmp_path / "settlements")
    catalog = _Catalog(ids={1, 2}, completed={1})  # event 2 still in progress
    app.dependency_overrides[get_board_archive] = lambda: boards
    app.dependency_overrides[get_settlement_archive] = lambda: settlements
    app.dependency_overrides[get_catalog_service] = lambda: catalog
    monkeypatch.setattr(
        analytics_module,
        "get_settings",
        lambda: SimpleNamespace(admin_api_token="secret", data_provider="mock"),
    )
    with TestClient(app) as c:
        yield c, settlements, catalog
    for dep in (get_board_archive, get_settlement_archive, get_catalog_service):
        app.dependency_overrides.pop(dep, None)


async def _seed(app: FastAPI) -> None:
    boards = app.dependency_overrides[get_board_archive]()
    await boards.persist(_board(1))
    await boards.persist(_board(2))


def test_requires_admin_token(settle_ctx) -> None:
    client, _, _ = settle_ctx
    assert client.post(_URL).status_code == 404
    assert client.post(_URL, headers={"X-Admin-Token": "nope"}).status_code == 404


async def test_settles_completed_events_only_then_is_idempotent(settle_ctx, app) -> None:
    client, settlements, _ = settle_ctx
    await _seed(app)

    first = client.post(_URL, headers={"X-Admin-Token": "secret"}).json()
    assert first["available"] is True
    assert first["events_graded"] == 1  # only the completed event grades
    assert first["settlements_total"] == 1
    assert [e["tournament_id"] for e in first["newly_settled"]] == [1]
    assert first["newly_settled"][0]["players"] == 3

    second = client.post(_URL, headers={"X-Admin-Token": "secret"}).json()
    assert second["newly_settled"] == []  # nothing new to pin
    assert second["settlements_total"] == 1
    assert second["events_graded"] == 1
    assert len(await settlements.list_all()) == 1


async def test_a_newly_completed_event_is_settled_on_the_next_run(settle_ctx, app) -> None:
    """The Monday-run case: an event that finished since the last run."""
    client, settlements, catalog = settle_ctx
    await _seed(app)
    client.post(_URL, headers={"X-Admin-Token": "secret"})

    catalog._completed.add(2)  # event 2 has now finished
    run = client.post(_URL, headers={"X-Admin-Token": "secret"}).json()
    assert [e["tournament_id"] for e in run["newly_settled"]] == [2]
    assert run["events_graded"] == 2
    assert run["settlements_total"] == 2
    assert {r.tournament_id for r in await settlements.list_all()} == {1, 2}

    # And it is not re-reported on the run after that.
    again = client.post(_URL, headers={"X-Admin-Token": "secret"}).json()
    assert again["newly_settled"] == []
    assert again["events_graded"] == 2


def test_empty_archive_reports_unavailable_rather_than_failing(settle_ctx) -> None:
    client, _, _ = settle_ctx
    body = client.post(_URL, headers={"X-Admin-Token": "secret"}).json()
    assert body == {
        "available": False,
        "events_graded": 0,
        "settlements_total": 0,
        "newly_settled": [],
    }
