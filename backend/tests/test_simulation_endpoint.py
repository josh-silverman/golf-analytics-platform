"""Endpoint tests for GET /api/v1/simulations/{tournament_id}."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from app.api.v1.deps import get_simulation_service
from app.simulation.engine import SimulationOutcome
from app.simulation.service import TournamentSimulation

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI


def _simulation(tid: int = 1) -> TournamentSimulation:
    return TournamentSimulation(
        tournament_id=tid,
        tournament_name="The Showcase",
        as_of=date(2026, 5, 30),
        n_iterations=10_000,
        score_std=3.3,
        outcomes=(
            SimulationOutcome(
                player_id=10,
                player_name="Alice Ace",
                win_prob=0.12,
                top_5_prob=0.38,
                top_10_prob=0.55,
                top_20_prob=0.75,
                make_cut_prob=0.90,
                expected_score=-2.0,
            ),
            SimulationOutcome(
                player_id=11,
                player_name="Bob Birdie",
                win_prob=0.05,
                top_5_prob=0.20,
                top_10_prob=0.35,
                top_20_prob=0.55,
                make_cut_prob=0.80,
                expected_score=-0.5,
            ),
        ),
    )


class _StubService:
    def __init__(self, *, found: bool = True) -> None:
        self._found = found

    async def simulate_tournament(
        self, tournament_id: int, *, as_of: date, rng: object = None
    ) -> TournamentSimulation | None:
        return _simulation(tournament_id) if self._found else None


@pytest.fixture
def sim_client(app: FastAPI) -> Iterator[TestClient]:
    app.dependency_overrides[get_simulation_service] = lambda: _StubService(found=True)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_simulation_service, None)


@pytest.fixture
def missing_client(app: FastAPI) -> Iterator[TestClient]:
    app.dependency_overrides[get_simulation_service] = lambda: _StubService(found=False)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_simulation_service, None)


def test_simulation_endpoint_returns_full_payload(sim_client: TestClient) -> None:
    r = sim_client.get("/api/v1/simulations/1")
    assert r.status_code == 200
    body = r.json()
    assert body["tournament_id"] == 1
    assert body["tournament_name"] == "The Showcase"
    assert body["n_iterations"] == 10_000
    assert body["score_std"] == pytest.approx(3.3)
    assert len(body["outcomes"]) == 2
    alice = body["outcomes"][0]
    assert alice["player_name"] == "Alice Ace"
    assert alice["win_prob"] == pytest.approx(0.12)
    assert alice["expected_score"] == pytest.approx(-2.0)


def test_simulation_endpoint_404_for_unknown_tournament(
    missing_client: TestClient,
) -> None:
    r = missing_client.get("/api/v1/simulations/999")
    assert r.status_code == 404


def test_simulation_probabilities_are_in_schema_bounds(sim_client: TestClient) -> None:
    r = sim_client.get("/api/v1/simulations/1")
    body = r.json()
    for o in body["outcomes"]:
        for key in ("win_prob", "top_5_prob", "top_10_prob", "top_20_prob", "make_cut_prob"):
            assert 0.0 <= o[key] <= 1.0
