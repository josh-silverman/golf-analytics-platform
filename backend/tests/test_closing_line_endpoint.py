"""Endpoint tests for the weekly closing-line capture (A5).

Pins what the cron depends on: the admin gate, the 409 for a provider with
no outright feed, and that ``healthy`` is the single field the workflow can
key its exit status off.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

import app.api.v1.analytics as analytics_module
from app.api.v1.deps import (
    get_catalog_service,
    get_closing_line_archive,
)
from app.domain.enums import TournamentStatus
from app.domain.models import Page, Tournament
from app.providers.factory import get_data_provider
from app.services.closing_line_archive import FileClosingLineArchive
from tests.test_closing_line_archive import _feeds

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

_URL = "/api/v1/analytics/closing-lines/capture"
_START = date(2026, 8, 27)
# reference_today() returns the mock provider's fixed anchor date, so the
# stub tournament is dated relative to it rather than to the real calendar
# (docs/ledger.md §3.5).
_TODAY = date(2026, 6, 3)


class _Catalog:
    def __init__(self, status: TournamentStatus) -> None:
        self._status = status

    async def list_tournaments(
        self, *, status: TournamentStatus | None = None, limit: int = 50, **_: object
    ) -> Page[Tournament]:
        if status is not None and status != self._status:
            return Page(items=[], next_cursor=None, has_more=False)
        return Page(
            items=[
                Tournament(
                    id=901,
                    course_id=1,
                    name="TOUR Championship",
                    season=2026,
                    start_date=_START,
                    end_date=_START,
                    purse=None,
                    field_strength=None,
                    status=self._status,
                )
            ],
            next_cursor=None,
            has_more=False,
        )


class _Provider:
    """A provider that has the outright feed."""

    async def fetch_live_outrights(self, market: str) -> dict[str, Any]:
        return _feeds().get(market, {})


class _FeedlessProvider:
    """A provider without one — the mock, in practice."""


@pytest.fixture
def ctx(app: FastAPI, monkeypatch, tmp_path) -> Iterator[tuple[TestClient, Any]]:
    archive = FileClosingLineArchive(tmp_path / "closing")
    app.dependency_overrides[get_closing_line_archive] = lambda: archive
    app.dependency_overrides[get_catalog_service] = lambda: _Catalog(TournamentStatus.UPCOMING)
    app.dependency_overrides[get_data_provider] = _Provider
    monkeypatch.setattr(
        analytics_module,
        "get_settings",
        lambda: SimpleNamespace(admin_api_token="secret", data_provider="mock"),
    )
    monkeypatch.setattr(analytics_module, "reference_today", lambda: _TODAY)
    with TestClient(app) as c:
        yield c, archive
    for dep in (get_closing_line_archive, get_catalog_service, get_data_provider):
        app.dependency_overrides.pop(dep, None)


def test_requires_admin_token(ctx) -> None:
    client, _ = ctx
    assert client.post(_URL).status_code == 404
    assert client.post(_URL, headers={"X-Admin-Token": "nope"}).status_code == 404


def test_captures_then_is_idempotent(ctx) -> None:
    client, archive = ctx
    first = client.post(_URL, headers={"X-Admin-Token": "secret"}).json()
    assert first["outcome"] == "captured"
    assert first["healthy"] is True
    assert first["event_name"] == "TOUR Championship"
    assert first["tournament_id"] == 901
    assert first["markets_offered"] == 4  # no-cut event: make_cut not offered

    second = client.post(_URL, headers={"X-Admin-Token": "secret"}).json()
    assert second["outcome"] == "already_captured"
    assert second["healthy"] is True


def test_refuses_a_started_event_and_reports_it_as_unhealthy(app, ctx) -> None:
    """The field the workflow keys on. A refusal means this week's market
    baseline is gone for good, so it must not read as a quiet success."""
    client, archive = ctx
    app.dependency_overrides[get_catalog_service] = lambda: _Catalog(TournamentStatus.IN_PROGRESS)
    body = client.post(_URL, headers={"X-Admin-Token": "secret"}).json()
    assert body["outcome"] == "event_already_started"
    assert body["healthy"] is False


def test_provider_without_an_outright_feed_conflicts(app, ctx) -> None:
    client, _ = ctx
    app.dependency_overrides[get_data_provider] = _FeedlessProvider
    r = client.post(_URL, headers={"X-Admin-Token": "secret"})
    assert r.status_code == 409


def test_snapshot_shows_up_in_archive_inspect(ctx) -> None:
    """Verify against the record, not the capture response (docs/ledger.md §3.3)."""
    client, _ = ctx
    client.post(_URL, headers={"X-Admin-Token": "secret"})
    body = client.get(
        "/api/v1/analytics/archive/inspect", headers={"X-Admin-Token": "secret"}
    ).json()
    assert body["closing_lines"] == 1
    snap = body["closing_line_snapshots"][0]
    assert snap["event_name"] == "TOUR Championship"
    assert snap["tournament_id"] == 901
    offered = {m["market"]: m["offered"] for m in snap["markets"]}
    assert offered == {
        "win_prob": True,
        "top_5_prob": True,
        "top_10_prob": True,
        "top_20_prob": True,
        "make_cut_prob": False,
    }
    # A market the books do not offer is a fact about the event, not a fault,
    # so it must not drag the roll-up down — otherwise every no-cut event
    # would read as degraded.
    assert snap["status"] == "ok"
    assert snap["clean"] is True
    # Prices must never reach this response — it is read in public logs. Check
    # the actual leak vectors rather than the substring "prices", which now
    # legitimately appears as the `prices_rejected` count.
    blob = str(snap)
    for leaked in ("american", "devigged", "dg_baseline'", "bet365"):
        assert leaked not in blob


class _DecimalProvider:
    """Decimal odds on the win market only, American elsewhere.

    A *partial* format change on purpose: total breakage already fails loudly
    because nothing parses, while a single drifting market captures, reports
    healthy, and is pinned forever. That is the silent case worth a fixture.
    Values are what DataGolf actually returns for `odds_format=decimal` —
    floats, not strings (verified against the live feed 2026-08-24).
    """

    async def fetch_live_outrights(self, market: str) -> dict[str, Any]:
        if market != "win":
            return _feeds().get(market, {})
        return {
            "event_name": "TOUR Championship",
            "market": market,
            "last_updated": "2026-08-26 21:03:05 UTC",
            "books_offering": ["bet365"],
            "odds": [
                {
                    "dg_id": 18417,
                    "player_name": "Player, One",
                    "bet365": 4.2,
                    "datagolf": {"baseline": 5.697464628240422},
                }
            ],
        }


def test_strict_run_refuses_a_suspect_feed_and_says_it_is_retryable(app, ctx) -> None:
    client, archive = ctx
    app.dependency_overrides[get_data_provider] = _DecimalProvider
    body = client.post(f"{_URL}?allow_degraded=false", headers={"X-Admin-Token": "secret"}).json()
    assert body["outcome"] == "feed_suspect"
    assert body["healthy"] is False
    assert body["retryable"] is True
    assert body["status"] == "suspect_prices"
    assert body["prices_rejected"] == 2  # the book price and DataGolf's baseline
    assert body["allow_degraded"] is False


def test_inspect_surfaces_a_suspect_capture(app, ctx) -> None:
    """The status has to be readable from the record, not just the capture
    response — that is the lesson of the settle run that passed green."""
    client, _ = ctx
    app.dependency_overrides[get_data_provider] = _DecimalProvider
    captured = client.post(
        f"{_URL}?allow_degraded=true", headers={"X-Admin-Token": "secret"}
    ).json()
    assert captured["outcome"] == "captured"

    body = client.get(
        "/api/v1/analytics/archive/inspect", headers={"X-Admin-Token": "secret"}
    ).json()
    snap = body["closing_line_snapshots"][0]
    assert snap["status"] == "suspect_prices"
    assert snap["clean"] is False
    win = next(m for m in snap["markets"] if m["market"] == "win_prob")
    assert win["status"] == "suspect_prices"
    assert win["prices_rejected"] == 2
    assert win["baseline_rows"] == 0
