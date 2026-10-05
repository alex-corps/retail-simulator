from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import pytest
from psycopg import Connection

from retail_sim.core.stock import DayStock, NegativeStockError
from retail_sim.steps.s1_supplier import COLD_START_QUANTITY, run_supplier
from retail_sim.steps.s2_assortment import run_assortment
from retail_sim.steps.s3_replenish import ReplenishResult, rollback_replenish, run_replenish
from tests.integration.helpers import (
    insert_product,
    insert_storage_location,
    insert_store,
    insert_warehouse,
)

# 2026-06-01 понедельник (и поставка, и отгрузка), 2026-06-02 вторник.
MONDAY = date(2026, 6, 1)
TUESDAY = date(2026, 6, 2)
OUTSIDE_DAY = date(2026, 5, 10)
STOCK_DAY_BEFORE = date(2026, 5, 29)
SALE_DAY = date(2026, 5, 30)
STOCK_DAY_AFTER = date(2026, 5, 31)
STORE_TARGET_DAYS = 7
# ceil(3.50) = 4, цель 7 дней → 28.
PRIMARY_QUANTITY = 28
# Продажа 10 шт за 3 активных дня: ceil(10/3 * 7) = 24.
HISTORY_QUANTITY = 24
ASSORTMENT_AVG = Decimal("3.50")


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
                Decimal("450.50"),
                5000,
                Decimal("50.00"),
                Decimal("15000.00"),
                14,
                STORE_TARGET_DAYS,
            ),
        )


def _store(
    conn: Connection[Any],
    name: str,
) -> tuple[int, int, int, int]:
    warehouse_location_id = insert_storage_location(conn, "склад")
    warehouse_id = insert_warehouse(conn, warehouse_location_id, f"Склад {name}")
    store_location_id = insert_storage_location(conn, "магазин")
    store_id = insert_store(
        conn,
        storage_location_id=store_location_id,
        warehouse_id=warehouse_id,
        name=name,
    )
    return warehouse_id, warehouse_location_id, store_id, store_location_id


def _assortment(
    conn: Connection[Any],
    store_id: int,
    product_id: int,
    avg_daily_sales: Decimal = ASSORTMENT_AVG,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO store_assortment (store_id, product_id, avg_daily_sales)
            VALUES (%s, %s, %s)
            """,
            (store_id, product_id, avg_daily_sales),
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


def _transfer(
    op_day: date,
    product_id: int,
    storage_location_id: int,
    sender_location_id: int,
    receiver_location_id: int,
    quantity: int,
) -> tuple[Any, ...]:
    return (
        datetime.combine(op_day, time.min),
        op_day,
        product_id,
        storage_location_id,
        sender_location_id,
        receiver_location_id,
        quantity,
        "перемещение",
    )


def test_tuesday_drops_stale_shipment_and_keeps_return(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    milk_id = insert_product(db_conn, name="Молоко")
    bread_id = insert_product(db_conn, name="Хлеб")
    _warehouse_id, warehouse_location_id, _store_id, store_location_id = _store(db_conn, "Магазин")
    _movement(
        db_conn,
        TUESDAY,
        milk_id,
        store_location_id,
        10,
        "перемещение",
        warehouse_location_id,
        store_location_id,
    )
    _movement(
        db_conn,
        TUESDAY,
        milk_id,
        warehouse_location_id,
        -10,
        "перемещение",
        warehouse_location_id,
        store_location_id,
    )
    _movement(
        db_conn,
        TUESDAY,
        bread_id,
        store_location_id,
        -2,
        "перемещение",
        store_location_id,
        warehouse_location_id,
    )
    _movement(
        db_conn,
        TUESDAY,
        bread_id,
        warehouse_location_id,
        2,
        "перемещение",
        store_location_id,
        warehouse_location_id,
    )
    stock = DayStock(
        {
            (warehouse_location_id, milk_id): 0,
            (store_location_id, milk_id): 10,
            (warehouse_location_id, bread_id): 2,
        }
    )

    result = run_replenish(db_conn, TUESDAY, stock)

    assert result == ReplenishResult(0, 0, 0, 0)
    assert _movements(db_conn) == [
        _transfer(
            TUESDAY, bread_id, warehouse_location_id, store_location_id, warehouse_location_id, 2
        ),
        _transfer(
            TUESDAY, bread_id, store_location_id, store_location_id, warehouse_location_id, -2
        ),
    ]
    assert stock.current((store_location_id, milk_id)) == 0
    assert stock.current((warehouse_location_id, milk_id)) == 10
    assert stock.current((warehouse_location_id, bread_id)) == 2


def test_primary_receipt_ships_assortment_only(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn)
    milk_id = insert_product(db_conn, name="Молоко")
    bread_id = insert_product(db_conn, name="Хлеб")
    _warehouse_id, warehouse_location_id, store_id, store_location_id = _store(db_conn, "Магазин")
    _assortment(db_conn, store_id, milk_id)
    stock = DayStock(
        {
            (warehouse_location_id, milk_id): 100,
            (warehouse_location_id, bread_id): 50,
        }
    )

    result = run_replenish(db_conn, MONDAY, stock)

    assert result == ReplenishResult(1, 1, PRIMARY_QUANTITY, 0)
    assert _movements(db_conn) == [
        _transfer(
            MONDAY,
            milk_id,
            warehouse_location_id,
            warehouse_location_id,
            store_location_id,
            -PRIMARY_QUANTITY,
        ),
        _transfer(
            MONDAY,
            milk_id,
            store_location_id,
            warehouse_location_id,
            store_location_id,
            PRIMARY_QUANTITY,
        ),
    ]
    assert stock.current((store_location_id, milk_id)) == PRIMARY_QUANTITY
    assert stock.current((warehouse_location_id, milk_id)) == 100 - PRIMARY_QUANTITY
    assert stock.current((warehouse_location_id, bread_id)) == 50
    assert stock.current((store_location_id, bread_id)) == 0


def test_history_window_drives_quantity(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn)
    product_id = insert_product(db_conn, name="Молоко")
    _warehouse_id, warehouse_location_id, store_id, store_location_id = _store(db_conn, "Магазин")
    _assortment(db_conn, store_id, product_id, Decimal("99.00"))
    _snapshot(db_conn, STOCK_DAY_BEFORE, store_location_id, product_id, 4)
    _snapshot(db_conn, STOCK_DAY_AFTER, store_location_id, product_id, 5)
    # Снимок самого понедельника в окно 21 дня не входит.
    _snapshot(db_conn, MONDAY, store_location_id, product_id, 999)
    _movement(
        db_conn,
        SALE_DAY,
        product_id,
        store_location_id,
        -10,
        "продажа",
        store_location_id,
        None,
    )
    _movement(
        db_conn,
        OUTSIDE_DAY,
        product_id,
        store_location_id,
        -100,
        "продажа",
        store_location_id,
        None,
    )
    _movement(
        db_conn,
        MONDAY,
        product_id,
        store_location_id,
        -50,
        "продажа",
        store_location_id,
        None,
    )
    stock = DayStock({(warehouse_location_id, product_id): 100})

    result = run_replenish(db_conn, MONDAY, stock)

    shipped = [row for row in _movements(db_conn) if row[7] == "перемещение"]
    assert result == ReplenishResult(1, 1, HISTORY_QUANTITY, 0)
    assert shipped == [
        _transfer(
            MONDAY,
            product_id,
            warehouse_location_id,
            warehouse_location_id,
            store_location_id,
            -HISTORY_QUANTITY,
        ),
        _transfer(
            MONDAY,
            product_id,
            store_location_id,
            warehouse_location_id,
            store_location_id,
            HISTORY_QUANTITY,
        ),
    ]


def test_stock_without_sales_is_not_replenished(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn)
    product_id = insert_product(db_conn, name="Молоко")
    _warehouse_id, warehouse_location_id, store_id, store_location_id = _store(db_conn, "Магазин")
    _assortment(db_conn, store_id, product_id)
    stock = DayStock(
        {
            (warehouse_location_id, product_id): 100,
            (store_location_id, product_id): 8,
        }
    )

    result = run_replenish(db_conn, MONDAY, stock)

    assert result == ReplenishResult(0, 0, 0, 0)
    assert _movements(db_conn) == []
    assert stock.current((store_location_id, product_id)) == 8


def test_shortage_is_split_across_stores(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn)
    product_id = insert_product(db_conn, name="Молоко", avg_daily_sales=Decimal("1.00"))
    warehouse_location_id = insert_storage_location(db_conn, "склад")
    warehouse_id = insert_warehouse(db_conn, warehouse_location_id, "Склад")
    first_location_id = insert_storage_location(db_conn, "магазин")
    second_location_id = insert_storage_location(db_conn, "магазин")
    first_store_id = insert_store(
        db_conn,
        storage_location_id=first_location_id,
        warehouse_id=warehouse_id,
        name="Первый",
    )
    second_store_id = insert_store(
        db_conn,
        storage_location_id=second_location_id,
        warehouse_id=warehouse_id,
        name="Второй",
    )
    # ceil(1.00) * 7 дней = 7 на магазин, на складе только 10.
    _assortment(db_conn, first_store_id, product_id, Decimal("1.00"))
    _assortment(db_conn, second_store_id, product_id, Decimal("1.00"))
    stock = DayStock({(warehouse_location_id, product_id): 10})

    result = run_replenish(db_conn, MONDAY, stock)

    assert result == ReplenishResult(2, 2, 10, 1)
    assert stock.current((warehouse_location_id, product_id)) == 0
    assert stock.current((first_location_id, product_id)) == 5
    assert stock.current((second_location_id, product_id)) == 5
    shipped = {(row[3], row[4], row[5], row[6]) for row in _movements(db_conn)}
    assert shipped == {
        (warehouse_location_id, warehouse_location_id, first_location_id, -5),
        (first_location_id, warehouse_location_id, first_location_id, 5),
        (warehouse_location_id, warehouse_location_id, second_location_id, -5),
        (second_location_id, warehouse_location_id, second_location_id, 5),
    }


def test_rerun_replaces_shipment_and_keeps_return(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn)
    milk_id = insert_product(db_conn, name="Молоко")
    bread_id = insert_product(db_conn, name="Хлеб")
    _warehouse_id, warehouse_location_id, store_id, store_location_id = _store(db_conn, "Магазин")
    _assortment(db_conn, store_id, milk_id)
    _movement(
        db_conn,
        MONDAY,
        bread_id,
        store_location_id,
        -2,
        "перемещение",
        store_location_id,
        warehouse_location_id,
    )
    _movement(
        db_conn,
        MONDAY,
        bread_id,
        warehouse_location_id,
        2,
        "перемещение",
        store_location_id,
        warehouse_location_id,
    )
    stock = DayStock(
        {
            (warehouse_location_id, milk_id): 100,
            (warehouse_location_id, bread_id): 2,
        }
    )

    run_replenish(db_conn, MONDAY, stock)
    first = _movements(db_conn)
    again = run_replenish(db_conn, MONDAY, stock)

    assert again == ReplenishResult(1, 1, PRIMARY_QUANTITY, 0)
    assert _movements(db_conn) == first
    assert stock.current((store_location_id, milk_id)) == PRIMARY_QUANTITY
    assert stock.current((warehouse_location_id, milk_id)) == 100 - PRIMARY_QUANTITY
    assert stock.current((warehouse_location_id, bread_id)) == 2


def test_rerun_raises_when_shipment_was_sold(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn)
    product_id = insert_product(db_conn, name="Молоко")
    _warehouse_id, warehouse_location_id, store_id, store_location_id = _store(db_conn, "Магазин")
    _assortment(db_conn, store_id, product_id)
    stock = DayStock({(warehouse_location_id, product_id): 100})
    run_replenish(db_conn, MONDAY, stock)
    _movement(
        db_conn,
        MONDAY,
        product_id,
        store_location_id,
        -PRIMARY_QUANTITY,
        "продажа",
        store_location_id,
        None,
    )
    stock.apply((store_location_id, product_id), -PRIMARY_QUANTITY)

    with pytest.raises(NegativeStockError):
        run_replenish(db_conn, MONDAY, stock)


def test_chain_rerun_after_shipment_stays_consistent(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn)
    product_id = insert_product(db_conn, name="Молоко")
    _warehouse_id, warehouse_location_id, store_id, store_location_id = _store(db_conn, "Магазин")
    _assortment(db_conn, store_id, product_id)
    stock = DayStock({})

    def run_chain() -> ReplenishResult:
        rollback_replenish(db_conn, MONDAY, stock)
        run_supplier(db_conn, MONDAY, stock)
        run_assortment(db_conn, MONDAY, stock, 1)
        return run_replenish(db_conn, MONDAY, stock)

    first = run_chain()
    first_rows = _movements(db_conn)
    second = run_chain()

    assert first == ReplenishResult(1, 1, PRIMARY_QUANTITY, 0)
    assert second == first
    assert _movements(db_conn) == first_rows
    assert stock.current((warehouse_location_id, product_id)) == (
        COLD_START_QUANTITY - PRIMARY_QUANTITY
    )
    assert stock.current((store_location_id, product_id)) == PRIMARY_QUANTITY
