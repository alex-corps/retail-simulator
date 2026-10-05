from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(
        default="postgresql://postgres:postgres@localhost:5432/retail_sim",
        description="PostgreSQL connection string",
    )
    migrations_dir: str = Field(
        default="migrations",
        description="Path to SQL migrations directory",
    )
    seed: int = Field(
        default=42,
        description="Global random seed",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
