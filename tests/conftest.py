from __future__ import annotations

import psycopg
import pytest

from retail_sim.config import Settings, get_settings


def is_db_reachable(settings: Settings | None = None) -> bool:
    active_settings = settings or get_settings()
    try:
        with (
            psycopg.connect(active_settings.database_url, connect_timeout=1) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("SELECT 1;")
            return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def db_available() -> bool:
    return is_db_reachable()
