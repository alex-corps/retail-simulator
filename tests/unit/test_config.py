from __future__ import annotations

import os
from unittest import mock

from retail_sim.config import Settings, get_settings


def test_default_settings() -> None:
    settings = Settings()
    assert "postgresql://" in settings.database_url
    assert settings.migrations_dir == "migrations"
    assert settings.seed == 42


def test_custom_settings_override() -> None:
    settings = Settings(
        database_url="postgresql://user:pass@remote:5432/custom_db",
        migrations_dir="custom_migrations",
        seed=123,
    )
    assert settings.database_url == "postgresql://user:pass@remote:5432/custom_db"
    assert settings.migrations_dir == "custom_migrations"
    assert settings.seed == 123


def test_settings_from_environment() -> None:
    with mock.patch.dict(os.environ, {"DATABASE_URL": "postgresql://test:test@localhost:5432/env_db"}):
        settings = Settings()
        assert settings.database_url == "postgresql://test:test@localhost:5432/env_db"


def test_get_settings_cached() -> None:
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
