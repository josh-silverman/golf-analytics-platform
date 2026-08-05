from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from app.api.v1.deps import get_model_registry
from app.cache.redis import get_redis
from app.config import get_settings
from app.ml.registry import ModelRegistry  # noqa: TC001 — FastAPI resolves at runtime

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
