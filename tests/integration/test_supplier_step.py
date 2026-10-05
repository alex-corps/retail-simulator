from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import pytest
from psycopg import Connection

from retail_sim.core.stock import DayStock, NegativeStockError
from retail_sim.steps.s1_supplier import COLD_START_QUANTITY, SupplierResult, run_supplier
from tests.integration.helpers import insert_product, insert_storage_location, insert_warehouse

# 2026-06-01 понедельник, 2026-06-02 вторник. Окно расхода для понедельника: 11-31 мая.
MONDAY = date(2026, 6, 1)
TUESDAY = date(2026, 6, 2)
OUTSIDE_DAY = date(2026, 5, 10)
STOCK_DAY_BEFORE = date(2026, 5, 29)
OUTFLOW_DAY = date(2026, 5, 30)
STOCK_DAY_AFTER = date(2026, 5, 31)
TARGET_DAYS = 14
CURRENT_STOCK = 10
# Отгрузка 10 шт за 3 активных дня: ceil(10/3 * 14 - 10) = 37.
EXPECTED_ORDER = 37


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


def _warehouse(conn: Connection[Any], name: str) -> int:
    location_id = insert_storage_location(conn, "склад")
    insert_warehouse(conn, location_id, name)
    return location_id


def _parameters(conn: Connection[Any], target_days: int) -> None:
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
            (800, Decimal("450.50"), 5000, Decimal("50.00"), Decimal("15000.00"), target_days, 7),
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


def _movements(conn: Connection[Any]) -> list[tuple[Any, ...]]:
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
            ORDER BY storage_location_id, product_id, id
            """
        )
        return list(cur.fetchall())


def test_cold_start_fills_every_warehouse_and_sku(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    milk_id = insert_product(db_conn, name="Молоко")
    bread_id = insert_product(db_conn, name="Хлеб")
    first_location_id = _warehouse(db_conn, "Склад 1")
    second_location_id = _warehouse(db_conn, "Склад 2")
    stock = DayStock({})

    result = run_supplier(db_conn, TUESDAY, stock)

    midnight = datetime.combine(TUESDAY, time.min)
    expected = [
        (
            midnight,
            TUESDAY,
            product_id,
            location_id,
            None,
            location_id,
            COLD_START_QUANTITY,
            "приход",
        )
        for location_id in (first_location_id, second_location_id)
        for product_id in (milk_id, bread_id)
    ]
    assert result == SupplierResult(
        cold_start=True,
        warehouses_supplied=2,
        skus_received=4,
        units_received=4 * COLD_START_QUANTITY,
    )
    assert _movements(db_conn) == expected
    assert stock.current((first_location_id, milk_id)) == COLD_START_QUANTITY
    assert stock.current((second_location_id, bread_id)) == COLD_START_QUANTITY


def test_cold_start_rerun_replaces_receipts(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    product_id = insert_product(db_conn, name="Молоко")
    warehouse_location_id = _warehouse(db_conn, "Склад")
    stock = DayStock({})

    run_supplier(db_conn, TUESDAY, stock)
    first = _movements(db_conn)
    again = run_supplier(db_conn, TUESDAY, stock)

    assert again == SupplierResult(True, 1, 1, COLD_START_QUANTITY)
    assert _movements(db_conn) == first
    assert stock.current((warehouse_location_id, product_id)) == COLD_START_QUANTITY


def test_tuesday_with_history_does_not_receive(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    product_id = insert_product(db_conn, name="Молоко")
    warehouse_location_id = _warehouse(db_conn, "Склад")
    store_location_id = insert_storage_location(db_conn, "магазин")
    _movement(
        db_conn,
        OUTSIDE_DAY,
        product_id,
        warehouse_location_id,
        -4,
        "перемещение",
        warehouse_location_id,
        store_location_id,
    )
    stock = DayStock({(warehouse_location_id, product_id): 20})

    result = run_supplier(db_conn, TUESDAY, stock)

    assert result == SupplierResult(False, 0, 0, 0)
    assert len(_movements(db_conn)) == 1
    assert stock.current((warehouse_location_id, product_id)) == 20


def test_monday_orders_from_windowed_outflow(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn, TARGET_DAYS)
    ordered_id = insert_product(db_conn, name="Молоко")
    idle_id = insert_product(db_conn, name="Хлеб")
    warehouse_location_id = _warehouse(db_conn, "Склад")
    other_location_id = _warehouse(db_conn, "Пустой склад")
    store_location_id = insert_storage_location(db_conn, "магазин")
    _snapshot(db_conn, STOCK_DAY_BEFORE, warehouse_location_id, ordered_id, 4)
    _snapshot(db_conn, STOCK_DAY_AFTER, warehouse_location_id, ordered_id, 5)
    # Снимок самого понедельника в окно не входит.
    _snapshot(db_conn, MONDAY, warehouse_location_id, ordered_id, 999)
    _movement(
        db_conn,
        OUTFLOW_DAY,
        ordered_id,
        warehouse_location_id,
        -6,
        "перемещение",
        warehouse_location_id,
        store_location_id,
    )
    _movement(
        db_conn,
        OUTFLOW_DAY,
        ordered_id,
        warehouse_location_id,
        -4,
        "перемещение",
        warehouse_location_id,
        store_location_id,
    )
    # Возврат из магазина расходом склада не является.
    _movement(
        db_conn,
        OUTFLOW_DAY,
        ordered_id,
        warehouse_location_id,
        50,
        "перемещение",
        store_location_id,
        warehouse_location_id,
    )
    _movement(
        db_conn,
        OUTSIDE_DAY,
        ordered_id,
        warehouse_location_id,
        -100,
        "перемещение",
        warehouse_location_id,
        store_location_id,
    )
    stock = DayStock(
        {
            (warehouse_location_id, ordered_id): CURRENT_STOCK,
            (warehouse_location_id, idle_id): 0,
        }
    )

    result = run_supplier(db_conn, MONDAY, stock)

    receipts = [row for row in _movements(db_conn) if row[7] == "приход"]
    assert result == SupplierResult(False, 1, 1, EXPECTED_ORDER)
    assert receipts == [
        (
            datetime.combine(MONDAY, time.min),
            MONDAY,
            ordered_id,
            warehouse_location_id,
            None,
            warehouse_location_id,
            EXPECTED_ORDER,
            "приход",
        )
    ]
    assert stock.current((warehouse_location_id, ordered_id)) == CURRENT_STOCK + EXPECTED_ORDER
    assert stock.current((warehouse_location_id, idle_id)) == 0
    assert stock.current((other_location_id, ordered_id)) == 0


def test_monday_rerun_rewrites_the_same_receipts(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn, TARGET_DAYS)
    product_id = insert_product(db_conn, name="Молоко")
    warehouse_location_id = _warehouse(db_conn, "Склад")
    store_location_id = insert_storage_location(db_conn, "магазин")
    _snapshot(db_conn, STOCK_DAY_BEFORE, warehouse_location_id, product_id, 4)
    _snapshot(db_conn, STOCK_DAY_AFTER, warehouse_location_id, product_id, 5)
    _movement(
        db_conn,
        OUTFLOW_DAY,
        product_id,
        warehouse_location_id,
        -10,
        "перемещение",
        warehouse_location_id,
        store_location_id,
    )
    # Приход на магазин в пересчёт склада не входит.
    _movement(
        db_conn,
        MONDAY,
        product_id,
        store_location_id,
        3,
        "приход",
        None,
        store_location_id,
    )
    stock = DayStock({(warehouse_location_id, product_id): CURRENT_STOCK})

    run_supplier(db_conn, MONDAY, stock)
    first = _movements(db_conn)
    again = run_supplier(db_conn, MONDAY, stock)

    assert again == SupplierResult(False, 1, 1, EXPECTED_ORDER)
    assert _movements(db_conn) == first
    assert stock.current((warehouse_location_id, product_id)) == CURRENT_STOCK + EXPECTED_ORDER


def test_rerun_raises_when_receipt_was_already_shipped(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    product_id = insert_product(db_conn, name="Молоко")
    warehouse_location_id = _warehouse(db_conn, "Склад")
    store_location_id = insert_storage_location(db_conn, "магазин")
    stock = DayStock({})
    run_supplier(db_conn, TUESDAY, stock)
    key = (warehouse_location_id, product_id)
    _movement(
        db_conn,
        TUESDAY,
        product_id,
        warehouse_location_id,
        -COLD_START_QUANTITY,
        "перемещение",
        warehouse_location_id,
        store_location_id,
    )
    stock.apply(key, -COLD_START_QUANTITY)

    with pytest.raises(NegativeStockError):
        run_supplier(db_conn, TUESDAY, stock)
