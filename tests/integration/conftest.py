from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from psycopg import Connection

from retail_sim.config import get_settings
from retail_sim.db.connection import get_connection
from retail_sim.db.migrate import apply_migrations
from tests.conftest import is_db_reachable

pytestmark = pytest.mark.skipif(
    not is_db_reachable(),
    reason="PostgreSQL is not reachable",
)


@pytest.fixture
def db_conn() -> Iterator[Connection[Any]]:
    settings = get_settings()
    with get_connection(settings) as conn:
        apply_migrations(conn, Path(settings.migrations_dir))
        with conn.transaction(force_rollback=True):
            yield conn
