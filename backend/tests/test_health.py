from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from app.api.v1.deps import get_model_registry
from app.cache.redis import get_redis
from app.ml.registry import ModelRegistry, ModelVersion


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
