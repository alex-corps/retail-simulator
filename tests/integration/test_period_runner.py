from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import pytest
from psycopg import Connection

import retail_sim.simulation.period_runner as period_runner
from retail_sim.domain.enums import RunStatus
from retail_sim.repositories.runs import RunNotFoundError, advance_run, get_run, list_runs
from retail_sim.repositories.stock import get_latest_snapshot_date
from retail_sim.simulation.day_runner import DayResult
from retail_sim.simulation.period_runner import resume_start_date, run_period
from tests.integration.helpers import (
    insert_product,
    insert_storage_location,
    insert_store,
    insert_warehouse,
)

MONDAY = date(2026, 6, 1)
TUESDAY = date(2026, 6, 2)
WEDNESDAY = date(2026, 6, 3)
THURSDAY = date(2026, 6, 4)
SUNDAY = date(2026, 6, 7)
PRIOR = date(2026, 5, 31)
SEED = 7


def _isolate(conn: Connection[Any]) -> None:
    with conn.cursor() as cur:
        for table in (
            "receipt_lines",
            "receipts",
            "store_assortment",
            "inventory_movements",
            "daily_opening_stock",
            "simulation_runs",
            "sale_period_stores",
            "sale_periods",
            "stores",
            "warehouses",
            "storage_locations",
            "products",
            "calculation_parameters",
        ):
            cur.execute(f"DELETE FROM {table}")


def _parameters(conn: Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO calculation_parameters (
                avg_receipts_per_day,
                avg_receipt_amount,
                avg_sku_capacity,
                min_receipt_amount,
                max_receipt_amount,
                target_stock_days_warehouse,
                target_stock_days_store
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (100, Decimal("200.00"), 100, Decimal("50.00"), Decimal("1000.00"), 14, 7),
        )


def _network(conn: Connection[Any]) -> tuple[int, int, int]:
    insert_product(
        conn,
        category_l1="Food",
        category_l2="Dairy",
        name="Milk",
        retail_price=Decimal("80.00"),
        avg_daily_sales=Decimal("2.00"),
    )
    insert_product(
        conn,
        category_l1="Food",
        category_l2="Bread",
        name="Bread",
        retail_price=Decimal("40.00"),
        avg_daily_sales=Decimal("2.00"),
    )
    warehouse_location_id = insert_storage_location(conn, "склад")
    warehouse_id = insert_warehouse(conn, warehouse_location_id, "Склад")
    store_location_id = insert_storage_location(conn, "магазин")
    store_id = insert_store(
        conn,
        storage_location_id=store_location_id,
        warehouse_id=warehouse_id,
        name="Магазин",
        avg_receipts_per_day=Decimal("2.00"),
        sku_capacity=2,
        open_from=time(10, 0),
        open_to=time(21, 0),
    )
    return store_id, store_location_id, warehouse_location_id


def _assortment(conn: Connection[Any], store_id: int, product_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO store_assortment (store_id, product_id, avg_daily_sales)
            VALUES (%s, %s, %s)
            """,
            (store_id, product_id, Decimal("2.00")),
        )


def _receipt_movement(
    conn: Connection[Any],
    op_day: date,
    product_id: int,
    location_id: int,
    quantity: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO inventory_movements (
                op_ts,
                product_id,
                storage_location_id,
                sender_location_id,
                receiver_location_id,
                quantity,
                op_type
            ) VALUES (%s, %s, %s, NULL, %s, %s, 'приход')
            """,
            (datetime.combine(op_day, time.min), product_id, location_id, location_id, quantity),
        )


def _count(conn: Connection[Any], sql: str, params: tuple[Any, ...] = ()) -> int:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _movement_count(conn: Connection[Any], day: date) -> int:
    return _count(
        conn,
        "SELECT COUNT(*) FROM inventory_movements WHERE op_date = %s",
        (day,),
    )


def test_period_cold_start_writes_the_journal(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn)
    _network(db_conn)
    seen: list[DayResult] = []

    result = run_period(db_conn, MONDAY, SUNDAY, SEED, on_day=seen.append)

    assert result.run_id is not None
    assert result.days == 7
    assert result.receipts_created > 0
    assert seen[0].supplier.cold_start is True
    assert any(day.sales.receipts_created > 0 for day in seen)
    run = get_run(db_conn, result.run_id)
    assert run is not None
    assert run.status == RunStatus.COMPLETED
    assert run.days_total == 7
    assert run.days_done == 7
    assert run.last_done_date == SUNDAY
    assert run.seed == SEED
    assert run.finished_at is not None
    assert run.error_message is None


def test_period_rerun_replaces_rows(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn)
    store_id, _store_location_id, warehouse_location_id = _network(db_conn)
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM products ORDER BY id")
        product_ids = [int(row[0]) for row in cur.fetchall()]
    for product_id in product_ids:
        _assortment(db_conn, store_id, product_id)
        _receipt_movement(db_conn, PRIOR, product_id, warehouse_location_id, 1000)

    first = run_period(db_conn, MONDAY, SUNDAY, SEED)
    movements = _count(db_conn, "SELECT COUNT(*) FROM inventory_movements")
    receipts = _count(db_conn, "SELECT COUNT(*) FROM receipts")
    second = run_period(db_conn, MONDAY, SUNDAY, SEED)

    assert first.units_sold > 0
    assert second.units_sold == first.units_sold
    assert second.receipts_created == first.receipts_created
    assert _count(db_conn, "SELECT COUNT(*) FROM inventory_movements") == movements
    assert _count(db_conn, "SELECT COUNT(*) FROM receipts") == receipts


def test_resume_continues_after_an_unfinished_run(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn)
    _network(db_conn)
    finished = run_period(db_conn, MONDAY, TUESDAY, SEED)
    assert finished.run_id is not None
    assert resume_start_date(db_conn, MONDAY) == TUESDAY

    with db_conn.cursor() as cur:
        cur.execute(
            """
            UPDATE simulation_runs
            SET status = 'running', finished_at = NULL, error_message = NULL
            WHERE id = %s
            """,
            (finished.run_id,),
        )
    assert resume_start_date(db_conn, MONDAY) == WEDNESDAY
    before = _movement_count(db_conn, MONDAY)

    continued = run_period(db_conn, WEDNESDAY, THURSDAY, SEED)

    assert continued.days == 2
    assert _movement_count(db_conn, MONDAY) == before
    assert get_latest_snapshot_date(db_conn) == THURSDAY
    assert get_run(db_conn, finished.run_id) is not None


def test_resume_uses_the_latest_snapshot_without_an_active_run(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn)
    _network(db_conn)
    assert resume_start_date(db_conn, MONDAY) == MONDAY

    run_period(db_conn, MONDAY, WEDNESDAY, SEED, journal=False)

    assert resume_start_date(db_conn, MONDAY) == WEDNESDAY
    assert resume_start_date(db_conn, date(2026, 7, 1)) == date(2026, 7, 1)
    assert list_runs(db_conn) == []


def test_failed_day_marks_the_run_and_rolls_that_day_back(
    db_conn: Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolate(db_conn)
    _parameters(db_conn)
    _network(db_conn)
    original = period_runner.run_day

    def flaky(conn: Connection[Any], day: date, seed: int) -> DayResult:
        if day == TUESDAY:
            raise RuntimeError("injected failure")
        return original(conn, day, seed)

    monkeypatch.setattr(period_runner, "run_day", flaky)

    with pytest.raises(RuntimeError, match="injected failure"):
        run_period(db_conn, MONDAY, WEDNESDAY, SEED)

    runs = list_runs(db_conn)
    assert len(runs) == 1
    failed = runs[0]
    assert failed.status == RunStatus.FAILED
    assert failed.days_done == 1
    assert failed.last_done_date == MONDAY
    assert failed.error_message is not None
    assert "injected failure" in failed.error_message
    assert failed.finished_at is not None
    assert _count(
        db_conn,
        """
        SELECT COUNT(*)
        FROM receipts
        WHERE receipt_ts >= %s AND receipt_ts < %s
        """,
        (MONDAY, TUESDAY),
    ) > 0
    assert (
        _count(
            db_conn,
            """
            SELECT COUNT(*)
            FROM receipts
            WHERE receipt_ts >= %s AND receipt_ts < %s
            """,
            (TUESDAY, WEDNESDAY),
        )
        == 0
    )


def test_advance_run_rejects_an_unknown_id(db_conn: Connection[Any]) -> None:
    with pytest.raises(RunNotFoundError):
        advance_run(db_conn, 10**12, MONDAY)
