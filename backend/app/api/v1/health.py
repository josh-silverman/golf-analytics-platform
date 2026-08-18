from __future__ import annotations

from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis  # noqa: TC002 — FastAPI resolves at runtime

from app.api.v1.deps import get_board_archive, get_model_registry
from app.cache.redis import get_redis
from app.config import get_settings
from app.ml.registry import ModelRegistry  # noqa: TC001 — FastAPI resolves at runtime
from app.providers.base import DataProvider  # noqa: TC001 — FastAPI resolves at runtime
from app.providers.factory import get_data_provider
from app.services.board_archive import BoardArchive  # noqa: TC001 — FastAPI resolves at runtime

router = APIRouter(tags=["health"])
log = structlog.get_logger()


@router.get("/healthz", status_code=status.HTTP_200_OK)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(
    redis: Annotated[Redis, Depends(get_redis)],
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
) -> JSONResponse:
    """Can this service actually serve predictions right now?

    Checks the dependencies the serving path (``PredictionService``, the
    board archive, the caching layer) actually touches: Redis, and a loadable
    active model in the registry. Postgres is deliberately not checked — the
    serving path never queries it (``render.yaml``'s own deployment notes say
    so explicitly) — probing an unused dependency would leave this endpoint
    permanently red in production for no operational reason, which is exactly
    what the previous DB check did.
    """
    checks: dict[str, str] = {}

    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:  # noqa: BLE001 — readiness probe catches everything
        log.warning("readiness_redis_failed", error=str(exc))
        checks["redis"] = "error"

    try:
        active = registry.get_active(get_settings().active_model_name)
        checks["model"] = "ok" if active is not None else "error"
    except Exception as exc:  # noqa: BLE001 — readiness probe catches everything
        log.warning("readiness_model_failed", error=str(exc))
        checks["model"] = "error"

    all_ok = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "ready" if all_ok else "not_ready",
            "checks": checks,
        },
    )


@router.get("/status")
async def status_endpoint(
    provider: Annotated[DataProvider, Depends(get_data_provider)],
    registry: Annotated[ModelRegistry, Depends(get_model_registry)],
    archive: Annotated[BoardArchive, Depends(get_board_archive)],
) -> dict[str, Any]:
    """Human-facing snapshot for sanity-checking the live demo.

    Not a liveness/readiness probe (see ``/healthz`` / ``/readyz``) — this is
    for eyeballing before a demo: which model is serving and what it was
    trained through, whether DataGolf answers right now, and when a board was
    last successfully built. Every sub-check is independently best-effort so
    one failing dependency still reports what it can about the rest.
    """
    settings = get_settings()
    active = registry.get_active(settings.active_model_name)

    # Probes whichever provider is actually configured (Depends resolves the
    # real DataGolfProvider in production, MockDataProvider in dev/tests) — a
    # single light call rather than branching on ``settings.data_provider``,
    # so this reflects what the service can actually reach right now.
    try:
        await provider.list_players(limit=1)
        provider_reachable = "ok"
    except Exception as exc:  # noqa: BLE001 — status probe catches everything
        log.warning("status_provider_unreachable", error=str(exc))
        provider_reachable = "unreachable"

    last_board_build_at: str | None = None
    try:
        snapshots = await archive.list_all()
        if snapshots:
            last_board_build_at = max(s.captured_at for s in snapshots)
    except Exception as exc:  # noqa: BLE001 — status probe catches everything
        log.warning("status_board_archive_failed", error=str(exc))

    return {
        "model_name": settings.active_model_name,
        "model_version_id": active.version_id if active else None,
        "training_data_through": (active.training_data_through.isoformat() if active else None),
        "serving_strategy": settings.serving_strategy,
        "data_provider": settings.data_provider,
        "provider_reachable": provider_reachable,
        "last_board_build_at": last_board_build_at,
    }
