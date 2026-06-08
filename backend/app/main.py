from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.v1.router import router as api_v1_router
from app.config import get_settings
from app.logging import configure_logging


def _init_sentry(dsn: str | None, traces_sample_rate: float, environment: str) -> None:
    """Initialise Sentry SDK if a DSN is configured; no-op otherwise.

    FastAPI integration automatically captures unhandled exceptions and
    attaches request context to every event.  Performance tracing is
    enabled at ``traces_sample_rate`` (default 10%) so the Sentry
    dashboard shows p50/p99 latency for each endpoint.

    Set SENTRY_DSN via: fly secrets set SENTRY_DSN=https://...@sentry.io/...
    """
    if not dsn:
        return  # pragma: no cover
    import sentry_sdk  # noqa: PLC0415 — lazy; sentry is optional at runtime
    from sentry_sdk.integrations.fastapi import FastApiIntegration  # noqa: PLC0415
    from sentry_sdk.integrations.starlette import StarletteIntegration  # noqa: PLC0415

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_sample_rate,
        integrations=[
            StarletteIntegration(transaction_style="endpoint"),
            FastApiIntegration(transaction_style="endpoint"),
        ],
        # Don't send PII (player names etc.) to Sentry by default.
        send_default_pii=False,
    )


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    _init_sentry(
        settings.sentry_dsn,
        settings.sentry_traces_sample_rate,
        settings.environment,
    )
    log = structlog.get_logger()
    log.info(
        "app_starting",
        environment=settings.environment,
        version="0.1.0",
        sentry_enabled=settings.sentry_dsn is not None,
    )
    yield
    log.info("app_stopping")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PGA Tour Analytics API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.include_router(api_v1_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
