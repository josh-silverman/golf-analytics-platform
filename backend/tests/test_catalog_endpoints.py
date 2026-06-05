"""Smoke tests for /players, /tournaments, and /meta catalog endpoints.

The CatalogService dependency is replaced with a fast in-process stub so these
tests run in milliseconds — no real provider or database needed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI

from app.api.v1.deps import get_catalog_service
from app.domain.enums import EntryStatus, TournamentStatus
from app.domain.models import (
    DataFreshness,
    Page,
    Player,
    Round,
    Tournament,
    TournamentEntry,
)

# ---------------------------------------------------------------------------
# Fixture data — deterministic values used across all tests
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 6, 3, 12, 0, 0, tzinfo=UTC)

_PLAYER = Player(
    id=1,
    dg_id=100,
    full_name="Tiger Woods",
    country="USA",
    dob=date(1975, 12, 30),
    turned_pro=1996,
)

_TOURNAMENT = Tournament(
    id=1,
    course_id=1,
    name="The Masters",
    season=2026,
    start_date=date(2026, 4, 10),
    end_date=date(2026, 4, 13),
    purse=20_000_000,
    field_strength=None,
    status=TournamentStatus.COMPLETED,
)

_ENTRY = TournamentEntry(
    id=1,
    tournament_id=1,
    player_id=1,
    status=EntryStatus.MADE_CUT,
    final_position=1,
    final_score_to_par=-13,
    official_money_cents=360_000_000,
)

_ROUND = Round(
    id=1,
    entry_id=1,
    round_number=1,
    score=65,
    score_to_par=-7,
    tee_time=None,
    sg_ott=1.2,
    sg_app=1.5,
    sg_arg=0.8,
    sg_putt=0.9,
    sg_t2g=3.5,
    sg_total=4.4,
)

_FRESHNESS = DataFreshness(
    sources={"players": _NOW, "tournaments": _NOW, "rounds": _NOW}
)


# ---------------------------------------------------------------------------
# Stub CatalogService
# ---------------------------------------------------------------------------


class _StubCatalog:
    source_name = "mock"

    async def data_freshness(self) -> DataFreshness:
        return _FRESHNESS

    async def list_players(
        self, *, cursor: str | None = None, limit: int = 50
    ) -> Page[Player]:
        return Page(items=[_PLAYER], next_cursor=None, total=1)

    async def get_player(self, player_id: int) -> Player | None:
        return _PLAYER if player_id == 1 else None

    async def recent_rounds_for_player(
        self, player_id: int, *, limit: int = 20
    ) -> list[Round]:
        return [_ROUND]

    async def list_tournaments(
        self,
        *,
        season: int | None = None,
        status: TournamentStatus | None = None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> Page[Tournament]:
        return Page(items=[_TOURNAMENT], next_cursor=None, total=1)

    async def get_tournament(self, tournament_id: int) -> Tournament | None:
        return _TOURNAMENT if tournament_id == 1 else None

    async def get_tournament_field(
        self, tournament_id: int
    ) -> list[TournamentEntry]:
        return [_ENTRY]

    async def get_current_tournament(self) -> Tournament | None:
        return _TOURNAMENT


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def catalog_client(app: FastAPI) -> Iterator[TestClient]:
    app.dependency_overrides[get_catalog_service] = _StubCatalog
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_catalog_service, None)


# ---------------------------------------------------------------------------
# /meta
# ---------------------------------------------------------------------------


def test_data_freshness_shape(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/meta/data-freshness")
    assert r.status_code == 200
    body = r.json()
    assert "players" in body["sources"]
    assert "tournaments" in body["sources"]


# ---------------------------------------------------------------------------
# /players
# ---------------------------------------------------------------------------


def test_list_players_envelope(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/players")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body and "page" in body and "meta" in body
    assert body["page"]["total"] == 1
    assert body["data"][0]["full_name"] == "Tiger Woods"


def test_list_players_respects_limit(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/players?limit=5")
    assert r.status_code == 200


def test_get_player_found(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/players/1")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body and "meta" in body
    assert body["data"]["id"] == 1


def test_get_player_not_found(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/players/999")
    assert r.status_code == 404


def test_recent_rounds_found(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/players/1/recent-rounds")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body and "page" in body and "meta" in body
    assert len(body["data"]) == 1
    assert body["data"][0]["round_number"] == 1


def test_recent_rounds_player_not_found(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/players/999/recent-rounds")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# /tournaments
# ---------------------------------------------------------------------------


def test_list_tournaments_envelope(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/tournaments")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body and "page" in body and "meta" in body
    assert body["page"]["total"] == 1
    assert body["data"][0]["name"] == "The Masters"


def test_list_tournaments_status_filter(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/tournaments?status=completed")
    assert r.status_code == 200


def test_current_tournament_found(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/tournaments/current")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["id"] == 1


def test_get_tournament_found(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/tournaments/1")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["name"] == "The Masters"


def test_get_tournament_not_found(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/tournaments/999")
    assert r.status_code == 404


def test_get_tournament_field(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/tournaments/1/field")
    assert r.status_code == 200
    body = r.json()
    assert body["page"]["total"] == 1
    assert body["data"][0]["player_id"] == 1


def test_get_tournament_field_not_found(catalog_client: TestClient) -> None:
    r = catalog_client.get("/api/v1/tournaments/999/field")
    assert r.status_code == 404
