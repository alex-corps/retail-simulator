from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from retail_sim.config import get_settings
from retail_sim.db.connection import get_connection
from retail_sim.db.migrate import apply_migrations
from retail_sim.domain.enums import OptimizationFlag
from retail_sim.repositories.stores import StoreNotFoundError, list_stores, set_optimization_flag
from retail_sim.steps.s0_opening_stock import run_opening_stock
from retail_sim.steps.s1_supplier import run_supplier
from retail_sim.steps.s2_assortment import run_assortment


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

    assortment_parser = subparsers.add_parser("assortment", help="Store assortment commands")
    assortment_subparsers = assortment_parser.add_subparsers(
        dest="assortment_command",
        required=True,
    )

    build_assortment_parser = assortment_subparsers.add_parser(
        "build",
        help="Build assortment for one day (opening stock, then assortment)",
    )
    build_assortment_parser.add_argument("--date", type=date.fromisoformat, required=True)

    optimize_parser = assortment_subparsers.add_parser(
        "optimize",
        help="Request assortment optimization (sets flag to 1)",
    )
    optimize_target = optimize_parser.add_mutually_exclusive_group(required=True)
    optimize_target.add_argument("--store-id", type=int, nargs="+")
    optimize_target.add_argument("--all", action="store_true")

    supply_parser = subparsers.add_parser("supply", help="Supplier receipt commands")
    supply_subparsers = supply_parser.add_subparsers(dest="supply_command", required=True)
    run_supply_parser = supply_subparsers.add_parser(
        "run",
        help="Receive supplier goods for one day (opening stock, then receipts)",
    )
    run_supply_parser.add_argument("--date", type=date.fromisoformat, required=True)

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


def handle_assortment_build(args: argparse.Namespace) -> int:
    settings = get_settings()
    with get_connection(settings) as conn, conn.transaction():
        stock = run_opening_stock(conn, args.date)
        result = run_assortment(conn, args.date, stock, settings.seed)
    print(
        f"Built assortment for {result.stores_filled} store(s), "
        f"optimized {result.stores_optimized} store(s), "
        f"returned {result.skus_returned} SKU(s) to the warehouse."
    )
    return 0


def handle_supply_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    with get_connection(settings) as conn, conn.transaction():
        stock = run_opening_stock(conn, args.date)
        result = run_supplier(conn, args.date, stock)
    kind = "Cold start" if result.cold_start else "Supplier receipts"
    print(
        f"{kind}: {result.warehouses_supplied} warehouse(s), "
        f"{result.skus_received} SKU line(s), "
        f"{result.units_received} unit(s)."
    )
    return 0


def handle_assortment_optimize(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        with get_connection(settings) as conn, conn.transaction():
            if args.all:
                store_ids = [store.id for store in list_stores(conn)]
            else:
                store_ids = list(args.store_id)
            for store_id in store_ids:
                set_optimization_flag(conn, store_id, OptimizationFlag.REQUESTED)
    except StoreNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Requested assortment optimization for {len(store_ids)} store(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "db" and args.db_command == "migrate":
        return handle_db_migrate(args)
    if args.subcommand == "assortment" and args.assortment_command == "build":
        return handle_assortment_build(args)
    if args.subcommand == "assortment" and args.assortment_command == "optimize":
        return handle_assortment_optimize(args)
    if args.subcommand == "supply" and args.supply_command == "run":
        return handle_supply_run(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
