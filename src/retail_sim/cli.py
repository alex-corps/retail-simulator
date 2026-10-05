from __future__ import annotations

import argparse
import sys
from pathlib import Path

from retail_sim.config import get_settings
from retail_sim.db.connection import get_connection
from retail_sim.db.migrate import apply_migrations


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="retail-sim",
        description="Retail inventory movement simulator CLI",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    db_parser = subparsers.add_parser("db", help="Database management commands")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)

    migrate_parser = db_subparsers.add_parser(
        "migrate",
        help="Apply pending database migrations",
    )
    migrate_parser.add_argument(
        "--migrations-dir",
        type=Path,
        default=None,
        help="Path to migrations folder (overrides default/env)",
    )

    return parser


def handle_db_migrate(args: argparse.Namespace) -> int:
    settings = get_settings()
    migrations_dir = args.migrations_dir or Path(settings.migrations_dir)
    with get_connection(settings) as conn:
        applied = apply_migrations(conn, migrations_dir)
        if applied:
            print(f"Applied {len(applied)} migration(s): {', '.join(applied)}")
        else:
            print("No pending migrations. Database is up to date.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "db" and args.db_command == "migrate":
        return handle_db_migrate(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
