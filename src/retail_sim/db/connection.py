from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

import psycopg

from retail_sim.config import Settings, get_settings

if TYPE_CHECKING:
    from collections.abc import Generator

    from psycopg import Connection


@contextmanager
def get_connection(
    settings: Settings | None = None,
) -> Generator[Connection[Any], None, None]:
    active_settings = settings or get_settings()
    conn: Connection[Any] = psycopg.connect(active_settings.database_url)
    try:
        yield conn
    finally:
        conn.close()
