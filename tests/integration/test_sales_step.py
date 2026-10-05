from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from psycopg import Connection

from retail_sim.core.stock import DayStock
from retail_sim.steps.s0_opening_stock import run_opening_stock
from retail_sim.steps.s4_sales import SalesResult, run_sales
from tests.integration.helpers import (
    insert_product,
    insert_storage_location,
    insert_store,
    insert_warehouse,
)

MONDAY = date(2026, 6, 1)
TUESDAY = date(2026, 6, 2)
PREVIOUS_DAY = date(2026, 5, 31)
SEED = 7
OPENING_QTY = 3
RETAIL_PRICE = Decimal("100.00")


def _isolate(conn: Connection[Any]) -> None:
    with conn.cursor() as cur:
        for table in (
            "receipt_lines",
            "receipts",
            "store_assortment",
            "inventory_movements",
            "daily_opening_stock",
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
            (
                800,
                Decimal("1000.00"),
                5000,
                Decimal("300.00"),
                Decimal("5000.00"),
                14,
                7,
            ),
        )


def _store(conn: Connection[Any], name: str) -> tuple[int, int]:
    warehouse_location_id = insert_storage_location(conn, "склад")
    warehouse_id = insert_warehouse(conn, warehouse_location_id, f"Склад {name}")
    store_location_id = insert_storage_location(conn, "магазин")
    store_id = insert_store(
        conn,
        storage_location_id=store_location_id,
        warehouse_id=warehouse_id,
        name=name,
        avg_receipts_per_day=Decimal("4.00"),
        open_from=time(10, 0),
        open_to=time(21, 0),
    )
    return store_id, store_location_id


def _assortment(conn: Connection[Any], store_id: int, product_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO store_assortment (store_id, product_id, avg_daily_sales)
            VALUES (%s, %s, %s)
            """,
            (store_id, product_id, Decimal("3.50")),
        )


def _snapshot(
    conn: Connection[Any],
    stock_date: date,
    storage_location_id: int,
    product_id: int,
    quantity: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO daily_opening_stock (
                stock_date, storage_location_id, product_id, quantity
            ) VALUES (%s, %s, %s, %s)
            """,
            (stock_date, storage_location_id, product_id, quantity),
        )


def _movement(
    conn: Connection[Any],
    op_day: date,
    product_id: int,
    storage_location_id: int,
    quantity: int,
    op_type: str,
    sender_location_id: int | None,
    receiver_location_id: int | None,
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
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                datetime.combine(op_day, time.min),
                product_id,
                storage_location_id,
                sender_location_id,
                receiver_location_id,
                quantity,
                op_type,
            ),
        )


def _lines(conn: Connection[Any]) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                r.store_id,
                r.receipt_ts,
                l.product_id,
                l.quantity,
                l.sale_price,
                l.discount_pct,
                l.clearance_flag
            FROM receipt_lines AS l
            JOIN receipts AS r ON r.id = l.receipt_id
            ORDER BY r.store_id, r.receipt_ts, r.id, l.product_id
            """
        )
        return list(cur.fetchall())


def _sales(conn: Connection[Any], day: date) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                op_ts,
                op_date,
                product_id,
                storage_location_id,
                sender_location_id,
                receiver_location_id,
                quantity,
                op_type
            FROM inventory_movements
            WHERE op_type = 'продажа'
              AND op_date = %s
            ORDER BY op_ts, storage_location_id, product_id, id
            """,
            (day,),
        )
        return list(cur.fetchall())


def _receipt_count(conn: Connection[Any]) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM receipts")
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def _prepare(conn: Connection[Any]) -> tuple[int, int, int, int, int]:
    _isolate(conn)
    _parameters(conn)
    product_id = insert_product(conn, name="Молоко", retail_price=RETAIL_PRICE)
    store_id, store_location_id = _store(conn, "Магазин")
    empty_store_id, empty_location_id = _store(conn, "Пустой")
    _assortment(conn, store_id, product_id)
    _assortment(conn, empty_store_id, product_id)
    _snapshot(conn, MONDAY, store_location_id, product_id, OPENING_QTY)
    _movement(
        conn,
        PREVIOUS_DAY,
        product_id,
        store_location_id,
        -1,
        "продажа",
        store_location_id,
        None,
    )
    return product_id, store_id, store_location_id, empty_store_id, empty_location_id


def test_sales_write_receipts_lines_and_movements(db_conn: Connection[Any]) -> None:
    product_id, store_id, store_location_id, empty_store_id, _empty_location_id = _prepare(db_conn)
    stock = DayStock({(store_location_id, product_id): OPENING_QTY})

    result = run_sales(db_conn, MONDAY, stock, SEED)

    assert result == SalesResult(
        stores_with_sales=1,
        receipts_created=1,
        lines_created=1,
        units_sold=OPENING_QTY,
        revenue=RETAIL_PRICE * OPENING_QTY,
    )
    assert stock.current((store_location_id, product_id)) == 0
    lines = _lines(db_conn)
    assert len(lines) == 1
    line_store_id, receipt_ts, line_product_id, quantity, sale_price, discount, clearance = lines[0]
    assert line_store_id == store_id
    assert line_store_id != empty_store_id
    assert receipt_ts.date() == MONDAY
    assert time(10, 0) <= receipt_ts.time() <= time(21, 0)
    assert line_product_id == product_id
    assert quantity == OPENING_QTY
    assert sale_price == RETAIL_PRICE
    assert discount == 0
    assert clearance == 0
    sales = _sales(db_conn, MONDAY)
    assert sales == [
        (
            receipt_ts,
            MONDAY,
            product_id,
            store_location_id,
            store_location_id,
            None,
            -OPENING_QTY,
            "продажа",
        )
    ]
    assert sum(row[6] for row in sales) == -sum(row[3] for row in lines)
    assert len(_sales(db_conn, PREVIOUS_DAY)) == 1


def test_sales_rerun_replaces_day_and_next_opening_subtracts_once(
    db_conn: Connection[Any],
) -> None:
    product_id, _store_id, store_location_id, _empty_store_id, _empty_location_id = _prepare(
        db_conn
    )
    stock = DayStock({(store_location_id, product_id): OPENING_QTY})

    first = run_sales(db_conn, MONDAY, stock, SEED)
    first_lines = _lines(db_conn)
    assert _receipt_count(db_conn) == 1

    second = run_sales(db_conn, MONDAY, stock, SEED)

    assert second == first
    assert _lines(db_conn) == first_lines
    assert _receipt_count(db_conn) == 1
    assert len(_sales(db_conn, MONDAY)) == 1
    assert len(_sales(db_conn, PREVIOUS_DAY)) == 1
    next_stock = run_opening_stock(db_conn, TUESDAY)
    assert next_stock.opening((store_location_id, product_id)) == OPENING_QTY - first.units_sold
