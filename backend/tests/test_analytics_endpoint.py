"""Endpoint test for /api/v1/analytics/calibration.

Stubs the model registry so the test builds a CalibrationReport by hand
rather than training a real model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest
from fastapi.testclient import TestClient

from app.api.v1.deps import get_model_registry
from app.ml.base import ConstantModel, Model
from app.ml.calibration import (
    CalibratedOutcomeModel,
    CalibrationReport,
    OutcomeCalibration,
    ReliabilityBin,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI


def _report() -> CalibrationReport:
    return CalibrationReport(
        outcomes=(
            OutcomeCalibration(
                outcome_key="win_prob",
                brier_raw=0.052,
                brier_calibrated=0.041,
                bins_raw=(
                    ReliabilityBin(0.0, 0.1, 0.05, 0.04, 120),
                    ReliabilityBin(0.9, 1.0, 0.95, 0.88, 8),
                ),
                bins_calibrated=(
                    ReliabilityBin(0.0, 0.1, 0.05, 0.048, 120),
                    ReliabilityBin(0.9, 1.0, 0.95, 0.93, 8),
                ),
            ),
        ),
        n_calibration_examples=200,
    )


def _calibrated_model() -> CalibratedOutcomeModel:
    return CalibratedOutcomeModel(
        base=ConstantModel({"win_prob": 0.05}),
        calibrators={},
        report=_report(),
    )


@dataclass
class _StubVersion:
    version_id: str


class _StubRegistry:
    def __init__(self, *, active: _StubVersion | None, model: Model | None) -> None:
        self._active = active
        self._model = model

    def get_active(self, name: str) -> _StubVersion | None:
        return self._active

    def load_artifact(self, version: Any, *, model_cls: Any = None) -> Model | None:
        return self._model


def _client(app: FastAPI, registry: _StubRegistry) -> Iterator[TestClient]:
    app.dependency_overrides[get_model_registry] = lambda: registry
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_model_registry, None)


@pytest.fixture
def calibrated_client(app: FastAPI) -> Iterator[TestClient]:
    registry = _StubRegistry(
        active=_StubVersion("abc123def456"), model=_calibrated_model()
    )
    yield from _client(app, registry)


@pytest.fixture
def no_model_client(app: FastAPI) -> Iterator[TestClient]:
    yield from _client(app, _StubRegistry(active=None, model=None))


@pytest.fixture
def uncalibrated_client(app: FastAPI) -> Iterator[TestClient]:
    registry = _StubRegistry(
        active=_StubVersion("v0"), model=ConstantModel({"win_prob": 0.05})
    )
    yield from _client(app, registry)


def test_calibration_endpoint_returns_report(calibrated_client: TestClient) -> None:
    r = calibrated_client.get("/api/v1/analytics/calibration")
    assert r.status_code == 200
    body = r.json()
    assert body["model_version_id"] == "abc123def456"
    assert body["n_calibration_examples"] == 200
    assert len(body["outcomes"]) == 1
    outcome = body["outcomes"][0]
    assert outcome["outcome_key"] == "win_prob"
    assert outcome["brier_calibrated"] < outcome["brier_raw"]
    assert len(outcome["bins_raw"]) == 2
    assert outcome["bins_raw"][0]["count"] == 120


def test_calibration_endpoint_404_when_no_active_model(
    no_model_client: TestClient,
) -> None:
    r = no_model_client.get("/api/v1/analytics/calibration")
    assert r.status_code == 404


def test_calibration_endpoint_409_when_model_uncalibrated(
    uncalibrated_client: TestClient,
) -> None:
    r = uncalibrated_client.get("/api/v1/analytics/calibration")
    assert r.status_code == 409
