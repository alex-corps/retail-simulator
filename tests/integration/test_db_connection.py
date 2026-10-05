from __future__ import annotations

from pathlib import Path

import pytest

from retail_sim.config import get_settings
from retail_sim.db.connection import get_connection
from retail_sim.db.migrate import apply_migrations, ensure_migrations_table, get_applied_migrations
from tests.conftest import is_db_reachable


@pytest.mark.skipif(not is_db_reachable(), reason="PostgreSQL is not reachable")
def test_db_connection_live() -> None:
    settings = get_settings()
    with get_connection(settings) as conn, conn.cursor() as cur:
        cur.execute("SELECT 1;")
        result = cur.fetchone()
        assert result is not None
        assert result[0] == 1


@pytest.mark.skipif(not is_db_reachable(), reason="PostgreSQL is not reachable")
def test_migrations_live_idempotent() -> None:
    settings = get_settings()
    migrations_dir = Path(settings.migrations_dir)
    with get_connection(settings) as conn:
        ensure_migrations_table(conn)
        applied_first = apply_migrations(conn, migrations_dir)
        applied_second = apply_migrations(conn, migrations_dir)
        # Second run should be idempotent and apply 0 migrations
        assert len(applied_second) == 0

        # Migration table should have records
        applied_set = get_applied_migrations(conn)
        assert len(applied_set) >= len(applied_first)
