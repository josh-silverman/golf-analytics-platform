from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI

from app.api.v1.router import router as api_v1_router
from app.config import get_settings
from app.logging import configure_logging


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(level=settings.log_level, log_format=settings.log_format)
    log = structlog.get_logger()
    log.info(
        "app_starting",
        environment=settings.environment,
        version="0.1.0",
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
