from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg import sql

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from psycopg import Connection


def copy_rows(
    conn: Connection[Any],
    table: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
) -> int:
    if not columns:
        raise ValueError("columns must not be empty")
    statement = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(table),
        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
    )
    written = 0
    with conn.cursor() as cur, cur.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)
            written += 1
    return written
