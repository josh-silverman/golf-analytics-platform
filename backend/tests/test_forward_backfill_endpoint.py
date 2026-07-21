"""Endpoint tests for the admin forward track-record backfill.

Covers the two behaviours worth pinning: the admin-token gate (the endpoint must
not exist without a configured secret) and idempotency (a second run captures
nothing and never overwrites). The heavy lifting — snapshot immutability and OOS
grading — is unit-tested in ``test_board_archive.py``; here the service, catalog
and archive are stubbed so no model or DataGolf call is involved.
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
    get_prediction_service,
)
from app.domain.enums import TournamentStatus
from app.domain.models import Page, Tournament

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

_BACKFILL_URL = "/api/v1/analytics/track-record/forward/backfill"


def _tournament(tid: int, start: str) -> Tournament:
    d = date.fromisoformat(start)
    return Tournament(
        id=tid, course_id=1, name=f"Event {tid}", season=2026,
        start_date=d, end_date=d, purse=None, field_strength=None,
        status=TournamentStatus.COMPLETED,
    )


def _preds(t: Tournament) -> SimpleNamespace:
    """A minimal duck-typed TournamentPredictions for snapshot_from_predictions."""
    return SimpleNamespace(
        tournament_id=t.id,
        tournament_name=t.name,
        as_of=t.start_date,
        model_name="golf_v1",
        model_version_id="path_a@v2",
        feature_set_hash="deadbeef",
        model_trained_through=date(2026, 5, 1),  # strictly before both events → OOS
        outcomes=[
            SimpleNamespace(
                player_id=10, win_prob=0.1, top_5_prob=0.2,
                top_10_prob=0.3, top_20_prob=0.4, make_cut_prob=0.9,
            )
        ],
    )


class _StubService:
    model_trained_through = date(2026, 5, 1)
    model_version_id = "path_a@v2"

    def __init__(self, tournaments: list[Tournament]) -> None:
        self._by_id = {t.id: t for t in tournaments}
        self.predict_calls = 0

    async def predict_tournament(self, tid: int, *, as_of: date) -> SimpleNamespace | None:
        self.predict_calls += 1
        t = self._by_id.get(tid)
        return _preds(t) if t is not None else None


class _StubCatalog:
    def __init__(self, tournaments: list[Tournament]) -> None:
        self._t = tournaments

    async def list_tournaments(self, *, status: object = None, limit: int = 200) -> Page:
        return Page(items=list(self._t), next_cursor=None, total=len(self._t))


class _MemArchive:
    """In-memory BoardArchive with first-write-wins immutability."""

    def __init__(self) -> None:
        self._d: dict[tuple[int, str | None], object] = {}

    async def has(self, tournament_id: int, model_version_id: str | None) -> bool:
        return (tournament_id, model_version_id) in self._d

    async def persist(self, snapshot: object) -> bool:
        key = (snapshot.tournament_id, snapshot.model_version_id)  # type: ignore[attr-defined]
        if key in self._d:
            return False
        self._d[key] = snapshot
        return True

    async def list_all(self) -> list[object]:
        return list(self._d.values())


@pytest.fixture
def backfill_ctx(
    app: FastAPI, monkeypatch
) -> Iterator[tuple[TestClient, _StubService, _MemArchive]]:
    tournaments = [_tournament(101, "2026-05-15"), _tournament(102, "2026-05-22")]
    service = _StubService(tournaments)
    archive = _MemArchive()
    app.dependency_overrides[get_prediction_service] = lambda: service
    app.dependency_overrides[get_catalog_service] = lambda: _StubCatalog(tournaments)
    app.dependency_overrides[get_board_archive] = lambda: archive
    monkeypatch.setattr(
        analytics_module, "get_settings",
        lambda: SimpleNamespace(admin_api_token="secret", data_provider="mock"),
    )
    with TestClient(app) as c:
        yield c, service, archive
    for dep in (get_prediction_service, get_catalog_service, get_board_archive):
        app.dependency_overrides.pop(dep, None)


def test_backfill_rejects_missing_and_wrong_token(backfill_ctx) -> None:
    client, _, _ = backfill_ctx
    assert client.post(_BACKFILL_URL).status_code == 404
    r = client.post(_BACKFILL_URL, headers={"X-Admin-Token": "nope"})
    assert r.status_code == 404


def test_backfill_disabled_when_no_token_configured(backfill_ctx, monkeypatch) -> None:
    client, _, _ = backfill_ctx
    monkeypatch.setattr(
        analytics_module, "get_settings",
        lambda: SimpleNamespace(admin_api_token=None, data_provider="mock"),
    )
    r = client.post(_BACKFILL_URL, headers={"X-Admin-Token": "secret"})
    assert r.status_code == 404  # unset secret → endpoint doesn't exist


async def test_backfill_captures_then_is_idempotent(backfill_ctx) -> None:
    client, service, archive = backfill_ctx
    r = client.post(_BACKFILL_URL, headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    body = r.json()
    assert body["captured"] == 2
    assert {e["tournament_id"] for e in body["events"]} == {101, 102}
    snaps = await archive.list_all()
    assert len(snaps) == 2
    assert all(s.source == "backfilled" for s in snaps)  # type: ignore[attr-defined]

    # Second run: everything already captured → nothing new, nothing overwritten,
    # and the expensive board build is skipped by the pre-check.
    predicts_after_first = service.predict_calls
    r2 = client.post(_BACKFILL_URL, headers={"X-Admin-Token": "secret"})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["captured"] == 0
    assert body2["skipped"] == 2
    assert service.predict_calls == predicts_after_first  # no rebuilds
    assert len(await archive.list_all()) == 2
