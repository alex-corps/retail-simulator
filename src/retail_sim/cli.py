from __future__ import annotations

import argparse
import sys
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import TYPE_CHECKING

from retail_sim.config import get_settings
from retail_sim.db.connection import get_connection
from retail_sim.db.migrate import apply_migrations
from retail_sim.domain.enums import OptimizationFlag
from retail_sim.repositories.promo import insert_sale_period
from retail_sim.repositories.stores import StoreNotFoundError, list_stores, set_optimization_flag
from retail_sim.simulation.day_runner import run_day
from retail_sim.simulation.period_runner import resume_start_date, run_period
from retail_sim.steps.s0_opening_stock import run_opening_stock
from retail_sim.steps.s1_supplier import run_supplier
from retail_sim.steps.s2_assortment import run_assortment
from retail_sim.steps.s3_replenish import rollback_replenish, run_replenish

if TYPE_CHECKING:
    from retail_sim.simulation.day_runner import DayResult


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

    replenish_parser = subparsers.add_parser("replenish", help="Warehouse-to-store replenishment")
    replenish_subparsers = replenish_parser.add_subparsers(
        dest="replenish_command",
        required=True,
    )
    run_replenish_parser = replenish_subparsers.add_parser(
        "run",
        help="Replenish stores for one day (opening stock, supply, assortment, transfers)",
    )
    run_replenish_parser.add_argument("--date", type=date.fromisoformat, required=True)

    sales_parser = subparsers.add_parser("sales", help="In-store sales commands")
    sales_subparsers = sales_parser.add_subparsers(dest="sales_command", required=True)
    run_sales_parser = sales_subparsers.add_parser(
        "run",
        help="Sell for one day (opening stock, supply, assortment, replenishment, receipts)",
    )
    run_sales_parser.add_argument("--date", type=date.fromisoformat, required=True)

    simulate_parser = subparsers.add_parser(
        "simulate",
        help="Run the daily pipeline for a date range",
    )
    simulate_parser.add_argument("--from", dest="date_from", type=date.fromisoformat, required=True)
    simulate_parser.add_argument("--to", dest="date_to", type=date.fromisoformat, required=True)
    simulate_parser.add_argument(
        "--resume",
        action="store_true",
        help="Continue from an unfinished run or the latest opening-stock date",
    )
    simulate_parser.add_argument(
        "--no-journal",
        action="store_true",
        help="Do not write a simulation_runs row",
    )

    promo_parser = subparsers.add_parser("promo", help="Sale period commands")
    promo_subparsers = promo_parser.add_subparsers(dest="promo_command", required=True)
    add_promo_parser = promo_subparsers.add_parser("add", help="Add a sale period")
    add_promo_parser.add_argument(
        "--from",
        dest="date_from",
        type=date.fromisoformat,
        required=True,
    )
    add_promo_parser.add_argument(
        "--to",
        dest="date_to",
        type=date.fromisoformat,
        required=True,
    )
    add_promo_parser.add_argument("--factor", type=_parse_factor, required=True)
    promo_target = add_promo_parser.add_mutually_exclusive_group(required=True)
    promo_target.add_argument("--store-id", type=int, nargs="+")
    promo_target.add_argument("--all", action="store_true")

    return parser


def _parse_factor(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"invalid factor {value}") from exc


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


def handle_replenish_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    with get_connection(settings) as conn, conn.transaction():
        stock = run_opening_stock(conn, args.date)
        # Снимаем отгрузку до пересчёта прихода: иначе склад уйдёт в минус.
        rollback_replenish(conn, args.date, stock)
        supplier = run_supplier(conn, args.date, stock)
        assortment = run_assortment(conn, args.date, stock, settings.seed)
        result = run_replenish(conn, args.date, stock)
    kind = "Cold start" if supplier.cold_start else "Supplier receipts"
    print(
        f"{kind}: {supplier.warehouses_supplied} warehouse(s), "
        f"{supplier.skus_received} SKU line(s), "
        f"{supplier.units_received} unit(s)."
    )
    print(
        f"Built assortment for {assortment.stores_filled} store(s), "
        f"optimized {assortment.stores_optimized} store(s), "
        f"returned {assortment.skus_returned} SKU(s) to the warehouse."
    )
    print(
        f"Replenishment: {result.stores_supplied} store(s), "
        f"{result.skus_shipped} SKU line(s), "
        f"{result.units_shipped} unit(s), "
        f"{result.skus_short} short SKU(s)."
    )
    return 0


def handle_sales_run(args: argparse.Namespace) -> int:
    settings = get_settings()
    with get_connection(settings) as conn:
        result = run_day(conn, args.date, settings.seed)
    supplier = result.supplier
    assortment = result.assortment
    replenish = result.replenish
    sales = result.sales
    kind = "Cold start" if supplier.cold_start else "Supplier receipts"
    print(
        f"{kind}: {supplier.warehouses_supplied} warehouse(s), "
        f"{supplier.skus_received} SKU line(s), "
        f"{supplier.units_received} unit(s)."
    )
    print(
        f"Built assortment for {assortment.stores_filled} store(s), "
        f"optimized {assortment.stores_optimized} store(s), "
        f"returned {assortment.skus_returned} SKU(s) to the warehouse."
    )
    print(
        f"Replenishment: {replenish.stores_supplied} store(s), "
        f"{replenish.skus_shipped} SKU line(s), "
        f"{replenish.units_shipped} unit(s), "
        f"{replenish.skus_short} short SKU(s)."
    )
    print(
        f"Sales: {sales.stores_with_sales} store(s), "
        f"{sales.receipts_created} receipt(s), "
        f"{sales.lines_created} line(s), "
        f"{sales.units_sold} unit(s), "
        f"{sales.revenue} RUB."
    )
    return 0


def _print_simulated_day(result: DayResult) -> None:
    print(
        f"{result.day.isoformat()}: {result.sales.receipts_created} receipt(s), "
        f"{result.sales.units_sold} unit(s), "
        f"{result.sales.revenue} RUB."
    )


def handle_simulate(args: argparse.Namespace) -> int:
    settings = get_settings()
    with get_connection(settings) as conn:
        start = resume_start_date(conn, args.date_from) if args.resume else args.date_from
        if start > args.date_to:
            print(
                f"Nothing to simulate: {start.isoformat()} is after {args.date_to.isoformat()}."
            )
            return 0
        result = run_period(
            conn,
            start,
            args.date_to,
            settings.seed,
            journal=not args.no_journal,
            on_day=_print_simulated_day,
        )
    print(
        f"Period {start.isoformat()}..{args.date_to.isoformat()}: "
        f"{result.days} day(s), "
        f"{result.receipts_created} receipt(s), "
        f"{result.units_sold} unit(s), "
        f"{result.revenue} RUB."
    )
    return 0


def handle_promo_add(args: argparse.Namespace) -> int:
    settings = get_settings()
    try:
        with get_connection(settings) as conn, conn.transaction():
            if args.all:
                store_ids = [store.id for store in list_stores(conn)]
            else:
                store_ids = list(args.store_id)
            if not store_ids:
                raise ValueError("sale period must include at least one store")
            period = insert_sale_period(
                conn,
                args.date_from,
                args.date_to,
                args.factor,
                store_ids,
            )
    except StoreNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        f"Sale period {period.id}: {period.date_from.isoformat()}..{period.date_to.isoformat()}, "
        f"factor {period.price_factor}, {len(period.store_ids)} store(s)."
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
    if args.subcommand == "replenish" and args.replenish_command == "run":
        return handle_replenish_run(args)
    if args.subcommand == "sales" and args.sales_command == "run":
        return handle_sales_run(args)
    if args.subcommand == "simulate":
        return handle_simulate(args)
    if args.subcommand == "promo" and args.promo_command == "add":
        return handle_promo_add(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
