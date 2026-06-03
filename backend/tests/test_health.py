from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache.redis import get_redis
from app.db.session import get_session


def test_healthz_returns_ok(client: TestClient) -> None:
    response = client.get("/api/v1/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _override_deps(app: FastAPI, *, db_ok: bool, redis_ok: bool) -> None:
    async def fake_session() -> AsyncIterator[AsyncSession]:
        session = AsyncMock(spec=AsyncSession)
        if db_ok:
            session.execute = AsyncMock(return_value=None)
        else:
            session.execute = AsyncMock(side_effect=ConnectionError("db down"))
        yield session

    async def fake_redis() -> Redis:
        redis = AsyncMock(spec=Redis)
        if redis_ok:
            redis.ping = AsyncMock(return_value=True)
        else:
            redis.ping = AsyncMock(side_effect=ConnectionError("redis down"))
        return redis

    app.dependency_overrides[get_session] = fake_session
    app.dependency_overrides[get_redis] = fake_redis


def test_readyz_returns_ready_when_all_dependencies_healthy(
    app: FastAPI, client: TestClient
) -> None:
    _override_deps(app, db_ok=True, redis_ok=True)
    response = client.get("/api/v1/readyz")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"db": "ok", "redis": "ok"}


def test_readyz_returns_not_ready_when_db_fails(app: FastAPI, client: TestClient) -> None:
    _override_deps(app, db_ok=False, redis_ok=True)
    response = client.get("/api/v1/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"] == {"db": "error", "redis": "ok"}


def test_readyz_returns_not_ready_when_redis_fails(app: FastAPI, client: TestClient) -> None:
    _override_deps(app, db_ok=True, redis_ok=False)
    response = client.get("/api/v1/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"] == {"db": "ok", "redis": "error"}
