"""Endpoint test for /api/v1/predictions/{tournament_id}.

Stubs the PredictionService directly so the test doesn't touch the
registry or the FeatureExtractor.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

import pytest
from fastapi.testclient import TestClient

from app.api.v1.deps import get_prediction_service
from app.services.predictions import (
    PlayerOutcome,
    TournamentPredictions,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI


def _predictions(tournament_id: int = 1) -> TournamentPredictions:
    return TournamentPredictions(
        tournament_id=tournament_id,
        tournament_name="The Demo",
        as_of=date(2026, 5, 30),
        model_name="golf_v1",
        model_version_id="abc123def456",
        feature_set_hash="deadbeef",
        outcomes=(
            PlayerOutcome(
                player_id=12, player_name="Cara Chip",
                win_prob=0.08, top_5_prob=0.30, top_10_prob=0.45,
                top_20_prob=0.65, make_cut_prob=0.85,
            ),
            PlayerOutcome(
                player_id=10, player_name="Alice Ace",
                win_prob=0.04, top_5_prob=0.18, top_10_prob=0.30,
                top_20_prob=0.50, make_cut_prob=0.70,
            ),
        ),
    )


class _StubService:
    def __init__(self, *, found: bool = True) -> None:
        self._found = found

    async def predict_tournament(
        self, tournament_id: int, *, as_of: date
    ) -> TournamentPredictions | None:
        if not self._found:
            return None
        return _predictions(tournament_id)


@pytest.fixture
def found_client(app: FastAPI) -> Iterator[TestClient]:
    app.dependency_overrides[get_prediction_service] = lambda: _StubService(found=True)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_prediction_service, None)


@pytest.fixture
def missing_client(app: FastAPI) -> Iterator[TestClient]:
    app.dependency_overrides[get_prediction_service] = lambda: _StubService(found=False)
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_prediction_service, None)


def test_predictions_endpoint_returns_full_payload(found_client: TestClient) -> None:
    r = found_client.get("/api/v1/predictions/1")
    assert r.status_code == 200
    body = r.json()
    assert body["tournament_id"] == 1
    assert body["tournament_name"] == "The Demo"
    assert body["model_name"] == "golf_v1"
    assert body["model_version_id"] == "abc123def456"
    assert len(body["outcomes"]) == 2
    assert body["outcomes"][0]["player_name"] == "Cara Chip"


def test_predictions_endpoint_404s_for_unknown_tournament(
    missing_client: TestClient,
) -> None:
    r = missing_client.get("/api/v1/predictions/999")
    assert r.status_code == 404


def test_predictions_endpoint_validates_outcome_probabilities(
    found_client: TestClient,
) -> None:
    """Pydantic Field bounds catch impossible probabilities at response time."""
    r = found_client.get("/api/v1/predictions/1")
    body = r.json()
    for outcome in body["outcomes"]:
        for key in ("win_prob", "top_5_prob", "top_10_prob",
                    "top_20_prob", "make_cut_prob"):
            assert 0.0 <= outcome[key] <= 1.0
