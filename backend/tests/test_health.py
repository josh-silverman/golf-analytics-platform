from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from app.api.v1.deps import get_board_archive, get_model_registry
from app.cache.redis import get_redis
from app.ml.registry import ModelRegistry, ModelVersion
from app.providers.factory import get_data_provider
from app.services.board_archive import BoardSnapshot


def test_healthz_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _fake_active_version() -> ModelVersion:
    return ModelVersion(
        name="golf_v1",
        version_id="deadbeef1234",
        feature_set_hash="x",
        training_data_through=date(2026, 1, 1),
        hyperparameters={},
        metrics={},
        trained_at=datetime(2026, 1, 1),
        artifact_relpath="golf_v1/deadbeef1234/artifact.pkl",
    )


def _override_deps(app: FastAPI, *, model_ok: bool, redis_ok: bool) -> None:
    registry = MagicMock(spec=ModelRegistry)
    registry.get_active.return_value = _fake_active_version() if model_ok else None

    async def fake_redis() -> Redis:
        redis = AsyncMock(spec=Redis)
        if redis_ok:
            redis.ping = AsyncMock(return_value=True)
        else:
            redis.ping = AsyncMock(side_effect=ConnectionError("redis down"))
        return redis

    app.dependency_overrides[get_model_registry] = lambda: registry
    app.dependency_overrides[get_redis] = fake_redis


def test_readyz_returns_ready_when_all_dependencies_healthy(
    app: FastAPI, client: TestClient
) -> None:
    _override_deps(app, model_ok=True, redis_ok=True)
    response = client.get("/api/v1/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"redis": "ok", "model": "ok"}


def test_readyz_returns_not_ready_when_no_active_model(app: FastAPI, client: TestClient) -> None:
    _override_deps(app, model_ok=False, redis_ok=True)
    response = client.get("/api/v1/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"] == {"redis": "ok", "model": "error"}


def test_readyz_returns_not_ready_when_redis_fails(app: FastAPI, client: TestClient) -> None:
    _override_deps(app, model_ok=True, redis_ok=False)
    response = client.get("/api/v1/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"] == {"redis": "error", "model": "ok"}


class _StubProvider:
    """No-network stand-in — see the identical pattern in test_betting_endpoint.py."""

    def __init__(self, *, reachable: bool) -> None:
        self._reachable = reachable

    async def list_players(self, *, cursor: str | None = None, limit: int = 100) -> None:
        if not self._reachable:
            raise ConnectionError("datagolf unreachable")


def _fake_snapshot(captured_at: str) -> BoardSnapshot:
    return BoardSnapshot(
        tournament_id=1,
        tournament_name="Test Open",
        tournament_start_date="2026-08-13",
        model_name="golf_v1",
        model_version_id="deadbeef1234",
        feature_set_hash="x",
        model_trained_through="2026-01-01",
        as_of="2026-08-12",
        captured_at=captured_at,
        outcomes=(),
    )


def _override_status_deps(
    app: FastAPI, *, model_ok: bool, provider_reachable: bool, snapshots: list[BoardSnapshot]
) -> None:
    registry = MagicMock(spec=ModelRegistry)
    registry.get_active.return_value = _fake_active_version() if model_ok else None

    archive = AsyncMock()
    archive.list_all = AsyncMock(return_value=snapshots)

    app.dependency_overrides[get_model_registry] = lambda: registry
    app.dependency_overrides[get_data_provider] = lambda: _StubProvider(
        reachable=provider_reachable
    )
    app.dependency_overrides[get_board_archive] = lambda: archive


def test_status_reports_active_model_and_last_board(app: FastAPI, client: TestClient) -> None:
    _override_status_deps(
        app,
        model_ok=True,
        provider_reachable=True,
        snapshots=[
            _fake_snapshot("2026-08-12T10:00:00+00:00"),
            _fake_snapshot("2026-08-15T10:00:00+00:00"),
        ],
    )
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["model_version_id"] == "deadbeef1234"
    assert body["training_data_through"] == "2026-01-01"
    assert body["provider_reachable"] == "ok"
    assert body["last_board_build_at"] == "2026-08-15T10:00:00+00:00"


def test_status_reports_unreachable_provider_without_failing(
    app: FastAPI, client: TestClient
) -> None:
    _override_status_deps(app, model_ok=True, provider_reachable=False, snapshots=[])
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["provider_reachable"] == "unreachable"
    assert body["last_board_build_at"] is None


def test_status_handles_no_active_model(app: FastAPI, client: TestClient) -> None:
    _override_status_deps(app, model_ok=False, provider_reachable=True, snapshots=[])
    response = client.get("/api/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["model_version_id"] is None
    assert body["training_data_through"] is None
