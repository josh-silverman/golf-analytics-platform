from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    environment: Literal["development", "test", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    api_v1_prefix: str = "/api/v1"

    database_url: str = Field(
        default="postgresql+asyncpg://pga:pga@localhost:5433/pga",
        description=(
            "SQLAlchemy async URL for Postgres (asyncpg driver). Host port is "
            "5433 to avoid colliding with a system PostgreSQL on 5432."
        ),
    )
    redis_url: str = Field(default="redis://localhost:6379/0")

    # Data provider selection (doc 02 §5)
    data_provider: Literal["mock", "datagolf"] = "mock"
    data_provider_cache: bool = True
    datagolf_api_key: str | None = None
    mock_seed: int = Field(
        default=42,
        description="Root seed for the mock data generator — same seed → bit-identical data.",
    )

    # Model registry — doc 02 §6. Filesystem-backed until the model_versions
    # table lands; the abstraction is identical so the swap is mechanical.
    model_registry_path: str = Field(
        default="./models",
        description="Root directory for the on-disk model registry.",
    )
    active_model_name: str = Field(
        default="golf_v1",
        description=(
            "Name of the model the predictions endpoint serves. The fallback"
            " ConstantModel is used when no version is marked active."
        ),
    )
    serving_strategy: str = Field(
        default="path_a",
        description=(
            "How the predictions endpoint sources probabilities. 'path_a'"
            " (default, validated 2026-07): DataGolf-direct for covered players,"
            " the SG-only model for cold-start. 'stacked': the active v3 model"
            " over the whole field (the pre-Path-A behaviour). Head-to-head"
            " validation showed path_a matches/exceeds stacked on every market"
            " and resolves the win/top-5 loss."
        ),
    )
    prediction_boards_path: str = Field(
        default="./prediction_boards",
        description=(
            "Root directory for the forward out-of-sample prediction-board"
            " archive (boards captured pre-event, graded once trained-before)."
        ),
    )

    # Observability
    sentry_dsn: str | None = Field(
        default=None,
        description=(
            "Sentry DSN for error tracking and performance monitoring. "
            "When absent, Sentry is disabled (no-op). "
            "Set via: fly secrets set SENTRY_DSN=https://..."
        ),
    )
    sentry_traces_sample_rate: float = Field(
        default=0.1,
        description="Fraction of transactions sent to Sentry for performance monitoring.",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
