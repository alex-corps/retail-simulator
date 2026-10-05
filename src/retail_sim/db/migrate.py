from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg import ClientCursor

if TYPE_CHECKING:
    from pathlib import Path

    from psycopg import Connection

MIGRATIONS_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version VARCHAR(255) PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def ensure_migrations_table(conn: Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(MIGRATIONS_TABLE_DDL)
    conn.commit()


def get_applied_migrations(conn: Connection[Any]) -> set[str]:
    ensure_migrations_table(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_migrations ORDER BY version;")
        rows = cur.fetchall()
        return {str(row[0]) for row in rows}


def discover_migration_files(migrations_dir: Path) -> list[Path]:
    if not migrations_dir.exists():
        raise FileNotFoundError(f"Migrations directory does not exist: {migrations_dir}")
    if not migrations_dir.is_dir():
        raise NotADirectoryError(f"Migrations path is not a directory: {migrations_dir}")

    files = [p for p in migrations_dir.iterdir() if p.is_file() and p.suffix.lower() == ".sql"]
    return sorted(files, key=lambda p: p.name)


def apply_migrations(conn: Connection[Any], migrations_dir: Path) -> list[str]:
    ensure_migrations_table(conn)
    applied = get_applied_migrations(conn)
    # SELECT оставляет транзакцию открытой. Иначе migration() ниже — это savepoint,
    # и close() соединения откатывает уже «применённую» миграцию.
    conn.commit()
    available_files = discover_migration_files(migrations_dir)

    pending_files = [f for f in available_files if f.name not in applied]
    if not pending_files:
        return []

    newly_applied: list[str] = []
    for file_path in pending_files:
        sql = file_path.read_text(encoding="utf-8")
        # ClientCursor uses the simple query protocol, so one migration file
        # may contain more than one SQL statement.
        with conn.transaction(), ClientCursor(conn) as cur:
            if sql.strip():
                cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (version) VALUES (%s);",
                (file_path.name,),
            )
        newly_applied.append(file_path.name)

    return newly_applied
