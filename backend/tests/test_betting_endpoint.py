"""Endpoint tests for GET /api/v1/betting/edge/{tournament_id}."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from app.api.v1.deps import get_prediction_service
from app.providers.factory import get_data_provider
from app.services.predictions import PlayerOutcome, TournamentPredictions

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI


def _predictions(tid: int = 1) -> TournamentPredictions:
    return TournamentPredictions(
        tournament_id=tid,
        tournament_name="Eagle Invitational",
        as_of=date(2026, 6, 1),
        model_name="golf_v1",
        model_version_id="abc123def456",
        feature_set_hash="deadbeef",
        outcomes=tuple(
            PlayerOutcome(
                player_id=i,
                player_name=f"Player {i}",
                win_prob=max(0.01, 0.20 - i * 0.03),
                top_5_prob=max(0.05, 0.50 - i * 0.05),
                top_10_prob=max(0.10, 0.70 - i * 0.05),
                top_20_prob=max(0.20, 0.85 - i * 0.04),
                make_cut_prob=max(0.40, 0.95 - i * 0.03),
            )
            for i in range(5)
        ),
    )


class _StubService:
    def __init__(self, *, found: bool = True) -> None:
        self._found = found

    async def predict_tournament(
        self, tournament_id: int, *, as_of: date
    ) -> TournamentPredictions | None:
        return _predictions(tournament_id) if self._found else None


class _StubProvider:
    """No-network stand-in for the data provider the edge endpoint resolves.

    Without this override the endpoint resolves the real ``get_data_provider``
    (DATA_PROVIDER=datagolf), which builds a ``DataGolfProvider`` whose
    ``httpx.AsyncClient`` is created in the TestClient's portal loop and then
    orphaned — under ``filterwarnings=["error"]`` its GC "Event loop is closed"
    warning escalates to a non-deterministic ERROR. The endpoint only calls
    ``get_outright_odds``; returning ``None`` falls back to synthetic odds.
    """

    async def get_outright_odds(self, outcome_key: str) -> None:
        return None


@pytest.fixture
def edge_client(app: FastAPI) -> Iterator[TestClient]:
    app.dependency_overrides[get_prediction_service] = lambda: _StubService(found=True)
    app.dependency_overrides[get_data_provider] = lambda: _StubProvider()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_prediction_service, None)
    app.dependency_overrides.pop(get_data_provider, None)


@pytest.fixture
def missing_client(app: FastAPI) -> Iterator[TestClient]:
    app.dependency_overrides[get_prediction_service] = lambda: _StubService(found=False)
    app.dependency_overrides[get_data_provider] = lambda: _StubProvider()
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_prediction_service, None)
    app.dependency_overrides.pop(get_data_provider, None)


def test_edge_endpoint_returns_board(edge_client: TestClient) -> None:
    r = edge_client.get("/api/v1/betting/edge/1")
    assert r.status_code == 200
    body = r.json()
    assert body["tournament_id"] == 1
    assert body["tournament_name"] == "Eagle Invitational"
    assert body["outcome_key"] == "win_prob"
    assert "lines" in body
    assert "n_positive_ev" in body


def test_edge_lines_have_required_fields(edge_client: TestClient) -> None:
    r = edge_client.get("/api/v1/betting/edge/1")
    body = r.json()
    for line in body["lines"]:
        for field in (
            "player_id",
            "player_name",
            "model_prob",
            "implied_prob",
            "american_odds",
            "edge",
            "ev_per_dollar",
            "kelly_fraction",
        ):
            assert field in line, f"Missing field: {field}"


def test_edge_lines_sorted_by_ev_descending(edge_client: TestClient) -> None:
    r = edge_client.get("/api/v1/betting/edge/1")
    body = r.json()
    evs = [line["ev_per_dollar"] for line in body["lines"]]
    assert evs == sorted(evs, reverse=True)


def test_edge_404_for_missing_tournament(missing_client: TestClient) -> None:
    r = missing_client.get("/api/v1/betting/edge/999")
    assert r.status_code == 404


def test_edge_outcome_key_query_param(edge_client: TestClient) -> None:
    r = edge_client.get("/api/v1/betting/edge/1?outcome_key=top_5_prob")
    assert r.status_code == 200
    body = r.json()
    assert body["outcome_key"] == "top_5_prob"


def test_edge_invalid_outcome_key_returns_422(edge_client: TestClient) -> None:
    r = edge_client.get("/api/v1/betting/edge/1?outcome_key=bogus_prob")
    assert r.status_code == 422


def test_n_positive_ev_matches_positive_edge_count(edge_client: TestClient) -> None:
    r = edge_client.get("/api/v1/betting/edge/1")
    body = r.json()
    # MIN_EDGE = 0.005
    positive = sum(1 for line in body["lines"] if line["edge"] >= 0.005)
    assert body["n_positive_ev"] == positive


def test_probabilities_bounded(edge_client: TestClient) -> None:
    r = edge_client.get("/api/v1/betting/edge/1")
    body = r.json()
    for line in body["lines"]:
        assert 0.0 <= line["model_prob"] <= 1.0
        assert 0.0 <= line["implied_prob"] <= 1.0
        assert line["kelly_fraction"] >= 0.0
