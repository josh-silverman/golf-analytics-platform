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
        default="postgresql+asyncpg://pga:pga@localhost:5432/pga",
        description="SQLAlchemy async URL for Postgres (asyncpg driver).",
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
