"""Endpoint tests for the scheduled pre-event capture run (B1).

Pins the behaviours the cron depends on: the admin gate, idempotency,
covering *both* events of an opposite-field week rather than a single
"current" event, and reporting ``healthy: false`` when an event in the
window did not get a board so the workflow can fail loudly.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

import app.api.v1.analytics as analytics_module
from app.api.v1.deps import (
    get_board_archive,
    get_catalog_service,
    get_prediction_service,
)
from app.domain.enums import TournamentStatus
from app.domain.models import Page, Tournament
from app.services.board_archive import FileBoardArchive

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

_URL = "/api/v1/analytics/track-record/capture-upcoming"
_TODAY = date(2026, 6, 3)  # a Wednesday
_THURSDAY = date(2026, 6, 4)


def _tournament(tid: int, start: date, status=TournamentStatus.UPCOMING) -> Tournament:
    return Tournament(
        id=tid,
        course_id=1,
        name=f"Event {tid}",
        season=2026,
        start_date=start,
        end_date=start,
        purse=None,
        field_strength=None,
        status=status,
    )


class _StubService:
    model_trained_through = date(2026, 5, 1)
    model_version_id = "path_a@v2"

    def __init__(self, *, field_size: int = 3, empty_for: set[int] | None = None) -> None:
        self._field_size = field_size
        self._empty_for = empty_for or set()

    async def predict_tournament(self, tid: int, *, as_of: date):  # noqa: ANN202
        n = 0 if tid in self._empty_for else self._field_size
        return SimpleNamespace(
            tournament_id=tid,
            tournament_name=f"Event {tid}",
            as_of=as_of,
            model_name="golf_v1",
            model_version_id="path_a@v2",
            feature_set_hash="deadbeef",
            model_trained_through=date(2026, 5, 1),
            outcomes=[
                SimpleNamespace(
                    player_id=10 + i,
                    win_prob=0.1,
                    top_5_prob=0.2,
                    top_10_prob=0.3,
                    top_20_prob=0.4,
                    make_cut_prob=0.9,
                )
                for i in range(n)
            ],
            dg_direct_count=n,
        )


class _StubCatalog:
    def __init__(self, tournaments: list[Tournament]) -> None:
        self._t = tournaments

    async def list_tournaments(self, *, status: object = None, limit: int = 200) -> Page:
        items = [t for t in self._t if status is None or t.status == status]
        return Page(items=items, next_cursor=None, total=len(items))

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        return next((t for t in self._t if t.id == tournament_id), None)


def _ctx(app: FastAPI, monkeypatch, tmp_path, tournaments, service=None):  # noqa: ANN202
    archive = FileBoardArchive(tmp_path)
    app.dependency_overrides[get_prediction_service] = lambda: service or _StubService()
    app.dependency_overrides[get_catalog_service] = lambda: _StubCatalog(tournaments)
    app.dependency_overrides[get_board_archive] = lambda: archive
    monkeypatch.setattr(
        analytics_module,
        "get_settings",
        lambda: SimpleNamespace(admin_api_token="secret", data_provider="mock"),
    )
    monkeypatch.setattr(analytics_module, "reference_today", lambda: _TODAY)
    return archive


@pytest.fixture
def capture_ctx(app: FastAPI, monkeypatch, tmp_path) -> Iterator[tuple[TestClient, object]]:
    archive = _ctx(
        app,
        monkeypatch,
        tmp_path,
        [_tournament(1, _THURSDAY), _tournament(2, _THURSDAY)],  # opposite-field week
    )
    with TestClient(app) as c:
        yield c, archive
    for dep in (get_prediction_service, get_catalog_service, get_board_archive):
        app.dependency_overrides.pop(dep, None)


def test_requires_admin_token(capture_ctx) -> None:
    client, _ = capture_ctx
    assert client.post(_URL).status_code == 404
    assert client.post(_URL, headers={"X-Admin-Token": "nope"}).status_code == 404


async def test_captures_every_event_of_an_opposite_field_week(capture_ctx) -> None:
    client, archive = capture_ctx
    r = client.post(_URL, headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["examined"] == 2
    assert body["captured"] == 2
    assert body["healthy"] is True
    # Both events of the week, not just whichever one is "current".
    assert {e["tournament_id"] for e in body["events"]} == {1, 2}
    assert {s.tournament_id for s in await archive.list_all()} == {1, 2}


async def test_second_run_is_a_no_op(capture_ctx) -> None:
    client, archive = capture_ctx
    client.post(_URL, headers={"X-Admin-Token": "secret"})
    body = client.post(_URL, headers={"X-Admin-Token": "secret"}).json()
    assert body["captured"] == 0
    assert body["healthy"] is True  # an idempotent no-op is not a failure
    assert all(e["outcome"] == "already_captured" for e in body["events"])
    assert len(await archive.list_all()) == 2


def test_off_week_with_no_upcoming_events_is_healthy(app, monkeypatch, tmp_path) -> None:
    _ctx(app, monkeypatch, tmp_path, [])
    with TestClient(app) as client:
        body = client.post(_URL, headers={"X-Admin-Token": "secret"}).json()
    assert body == {"examined": 0, "captured": 0, "healthy": True, "events": []}


def test_event_beyond_the_lookahead_window_is_left_alone(app, monkeypatch, tmp_path) -> None:
    _ctx(app, monkeypatch, tmp_path, [_tournament(9, _TODAY + timedelta(days=20))])
    with TestClient(app) as client:
        body = client.post(_URL, headers={"X-Admin-Token": "secret"}).json()
    assert body["examined"] == 0  # next month's event is not pinned early


def test_same_day_start_is_not_even_attempted(app, monkeypatch, tmp_path) -> None:
    """The guard would refuse it, so the window excludes it rather than
    manufacturing a guaranteed unhealthy result every Wednesday-start week."""
    _ctx(app, monkeypatch, tmp_path, [_tournament(5, _TODAY)])
    with TestClient(app) as client:
        body = client.post(_URL, headers={"X-Admin-Token": "secret"}).json()
    assert body["examined"] == 0
    assert body["healthy"] is True


def test_unpublished_field_reports_unhealthy_so_the_job_fails_loudly(
    app, monkeypatch, tmp_path
) -> None:
    _ctx(
        app,
        monkeypatch,
        tmp_path,
        [_tournament(1, _THURSDAY), _tournament(2, _THURSDAY)],
        service=_StubService(empty_for={2}),
    )
    with TestClient(app) as client:
        body = client.post(_URL, headers={"X-Admin-Token": "secret"}).json()
    assert body["captured"] == 1
    assert body["healthy"] is False
    by_id = {e["tournament_id"]: e for e in body["events"]}
    assert by_id[1]["outcome"] == "captured"
    assert by_id[2]["outcome"] == "no_field"
