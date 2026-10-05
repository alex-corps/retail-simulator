from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from psycopg import Connection

from retail_sim.core.stock import DayStock
from retail_sim.domain.enums import OptimizationFlag
from retail_sim.repositories.stores import get_store
from retail_sim.steps.s0_opening_stock import run_opening_stock
from retail_sim.steps.s2_assortment import AssortmentResult, run_assortment
from tests.integration.helpers import (
    insert_product,
    insert_storage_location,
    insert_store,
    insert_warehouse,
)

DAY = date(2026, 6, 1)
PREVIOUS_DAY = date(2026, 5, 31)
SEED = 7


def _isolate(conn: Connection[Any]) -> None:
    with conn.cursor() as cur:
        for table in (
            "receipt_lines",
            "receipts",
            "store_assortment",
            "inventory_movements",
            "daily_opening_stock",
            "sale_period_stores",
            "sale_periods",
            "stores",
            "warehouses",
            "storage_locations",
            "products",
        ):
            cur.execute(f"DELETE FROM {table}")


def _catalog(conn: Connection[Any]) -> dict[str, int]:
    specs = (
        ("milk-low", "Dairy", "10.00"),
        ("milk-mid", "Dairy", "20.00"),
        ("milk-high", "Dairy", "30.00"),
        ("bread-low", "Bread", "1.00"),
        ("bread-mid", "Bread", "2.00"),
        ("bread-high", "Bread", "3.00"),
    )
    return {
        name: insert_product(
            conn,
            category_l1="Food",
            category_l2=category_l2,
            name=name,
            avg_daily_sales=Decimal(avg),
        )
        for name, category_l2, avg in specs
    }


def _store(
    conn: Connection[Any],
    *,
    sku_capacity: int,
    optimization_flag: int,
) -> tuple[int, int, int]:
    warehouse_location_id = insert_storage_location(conn, "склад")
    store_location_id = insert_storage_location(conn, "магазин")
    warehouse_id = insert_warehouse(conn, warehouse_location_id, "Склад S2")
    store_id = insert_store(
        conn,
        storage_location_id=store_location_id,
        warehouse_id=warehouse_id,
        name="Магазин S2",
        sku_capacity=sku_capacity,
        optimization_flag=optimization_flag,
    )
    return store_id, store_location_id, warehouse_location_id


def _insert_assortment(
    conn: Connection[Any],
    store_id: int,
    product_id: int,
    avg_daily_sales: Decimal,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO store_assortment (store_id, product_id, avg_daily_sales)
            VALUES (%s, %s, %s)
            """,
            (store_id, product_id, avg_daily_sales),
        )


def _insert_snapshot(
    conn: Connection[Any],
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
            (PREVIOUS_DAY, storage_location_id, product_id, quantity),
        )


def _assortment(conn: Connection[Any], store_id: int) -> list[tuple[Any, ...]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                assortment.product_id,
                assortment.avg_daily_sales,
                products.category_l2,
                products.avg_daily_sales
            FROM store_assortment AS assortment
            JOIN products ON products.id = assortment.product_id
            WHERE assortment.store_id = %s
            ORDER BY assortment.product_id
            """,
            (store_id,),
        )
        return list(cur.fetchall())


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
            ORDER BY id
            """
        )
        return list(cur.fetchall())


def test_new_store_receives_even_assortment_once(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _catalog(db_conn)
    store_id, _, _ = _store(db_conn, sku_capacity=4, optimization_flag=0)
    stock = run_opening_stock(db_conn, DAY)

    result = run_assortment(db_conn, DAY, stock, SEED)

    rows = _assortment(db_conn, store_id)
    assert result == AssortmentResult(stores_filled=1, stores_optimized=0, skus_returned=0)
    assert len(rows) == 4
    assert {row[2] for row in rows} == {"Dairy", "Bread"}
    assert [row[2] for row in rows].count("Dairy") == 2
    assert [row[2] for row in rows].count("Bread") == 2
    for _, store_avg, _, base_avg in rows:
        assert Decimal("0.69") * base_avg <= store_avg <= Decimal("1.31") * base_avg
    store = get_store(db_conn, store_id)
    assert store is not None
    assert store.optimization_flag == OptimizationFlag.IDLE

    again = run_assortment(db_conn, DAY, stock, SEED)

    assert again == AssortmentResult(0, 0, 0)
    assert _assortment(db_conn, store_id) == rows
    assert _movements(db_conn) == []


def test_requested_store_without_assortment_is_not_optimized_the_same_day(
    db_conn: Connection[Any],
) -> None:
    _isolate(db_conn)
    _catalog(db_conn)
    store_id, _, _ = _store(db_conn, sku_capacity=6, optimization_flag=1)

    result = run_assortment(db_conn, DAY, DayStock({}), SEED)

    store = get_store(db_conn, store_id)
    assert result == AssortmentResult(stores_filled=1, stores_optimized=0, skus_returned=0)
    assert store is not None
    assert store.optimization_flag == OptimizationFlag.REQUESTED
    assert len(_assortment(db_conn, store_id)) == 6
    assert _movements(db_conn) == []


def test_optimization_returns_delisted_stock_and_does_not_repeat(
    db_conn: Connection[Any],
) -> None:
    _isolate(db_conn)
    products = _catalog(db_conn)
    store_id, store_location_id, warehouse_location_id = _store(
        db_conn,
        sku_capacity=4,
        optimization_flag=1,
    )
    _insert_assortment(db_conn, store_id, products["milk-low"], Decimal("8.88"))
    _insert_assortment(db_conn, store_id, products["milk-high"], Decimal("4.00"))
    _insert_assortment(db_conn, store_id, products["bread-low"], Decimal("1.11"))
    _insert_assortment(db_conn, store_id, products["bread-high"], Decimal("2.22"))
    _insert_snapshot(db_conn, store_location_id, products["milk-low"], 5)
    _insert_snapshot(db_conn, store_location_id, products["milk-high"], 7)
    _insert_snapshot(db_conn, store_location_id, products["bread-high"], 4)
    stock = run_opening_stock(db_conn, DAY)

    result = run_assortment(db_conn, DAY, stock, SEED)

    assert result == AssortmentResult(stores_filled=0, stores_optimized=1, skus_returned=1)
    rows = {row[0]: row[1] for row in _assortment(db_conn, store_id)}
    assert set(rows) == {
        products["milk-high"],
        products["milk-mid"],
        products["bread-high"],
        products["bread-mid"],
    }
    assert rows[products["milk-high"]] == Decimal("4.00")
    assert rows[products["bread-high"]] == Decimal("2.22")
    assert Decimal("14.00") <= rows[products["milk-mid"]] <= Decimal("26.00")
    assert Decimal("1.40") <= rows[products["bread-mid"]] <= Decimal("2.60")
    movements = _movements(db_conn)
    assert len(movements) == 2
    assert {row[6] for row in movements} == {-5, 5}
    assert sum(row[6] for row in movements) == 0
    for op_ts, op_date, product_id, location_id, sender_id, receiver_id, _, op_type in movements:
        assert op_ts == datetime.combine(DAY, time.min)
        assert op_date == DAY
        assert product_id == products["milk-low"]
        assert sender_id == store_location_id
        assert receiver_id == warehouse_location_id
        assert op_type == "перемещение"
        assert location_id in {store_location_id, warehouse_location_id}
    assert stock.current((store_location_id, products["milk-low"])) == 0
    assert stock.current((warehouse_location_id, products["milk-low"])) == 5
    assert stock.current((store_location_id, products["milk-high"])) == 7
    store = get_store(db_conn, store_id)
    assert store is not None
    assert store.optimization_flag == OptimizationFlag.COMPLETED

    rebuilt = run_opening_stock(db_conn, DAY)
    again = run_assortment(db_conn, DAY, rebuilt, SEED)

    assert again == AssortmentResult(0, 0, 0)
    assert len(_movements(db_conn)) == 2
    assert rebuilt.current((store_location_id, products["milk-low"])) == 0
    assert rebuilt.current((warehouse_location_id, products["milk-low"])) == 5
