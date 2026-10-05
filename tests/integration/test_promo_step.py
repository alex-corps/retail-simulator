from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from typing import Any

import pytest
from psycopg import Connection

from retail_sim.core.promo import InvalidPriceFactorError
from retail_sim.core.stock import DayStock
from retail_sim.repositories.promo import effective_price_factors, insert_sale_period
from retail_sim.repositories.stores import StoreNotFoundError
from retail_sim.steps.s4_sales import run_sales
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
STOCK_QTY = 10_000
RETAIL_PRICE = Decimal("100.00")


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


def _units(lines: list[tuple[Any, ...]], store_id: int) -> int:
    return sum(int(row[3]) for row in lines if row[0] == store_id)


def _signature(lines: list[tuple[Any, ...]], store_id: int) -> list[tuple[Any, ...]]:
    return [row[1:] for row in lines if row[0] == store_id]


def test_insert_sale_period_rejects_bad_input(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    store_id, _location_id = _store(db_conn, "Магазин")

    with pytest.raises(InvalidPriceFactorError):
        insert_sale_period(db_conn, MONDAY, TUESDAY, Decimal("0"), [store_id])
    with pytest.raises(InvalidPriceFactorError):
        insert_sale_period(db_conn, MONDAY, TUESDAY, Decimal("1"), [store_id])
    with pytest.raises(ValueError, match="date_from"):
        insert_sale_period(db_conn, TUESDAY, MONDAY, Decimal("0.8"), [store_id])
    with pytest.raises(ValueError, match="at least one"):
        insert_sale_period(db_conn, MONDAY, TUESDAY, Decimal("0.8"), [])
    with pytest.raises(StoreNotFoundError):
        insert_sale_period(db_conn, MONDAY, TUESDAY, Decimal("0.8"), [999_999_999])

    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM sale_periods")
        row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == 0


def test_effective_factor_uses_smallest_and_inclusive_dates(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    store_id, _location_id = _store(db_conn, "Магазин")
    other_id, _other_location = _store(db_conn, "Сосед")

    insert_sale_period(db_conn, MONDAY, MONDAY, Decimal("0.8"), [store_id])
    insert_sale_period(db_conn, MONDAY, TUESDAY, Decimal("0.5"), [store_id, store_id])
    insert_sale_period(db_conn, PREVIOUS_DAY, PREVIOUS_DAY, Decimal("0.7"), [store_id])

    assert effective_price_factors(db_conn, MONDAY) == {store_id: Decimal("0.5000")}
    assert effective_price_factors(db_conn, TUESDAY) == {store_id: Decimal("0.5000")}
    assert effective_price_factors(db_conn, PREVIOUS_DAY) == {store_id: Decimal("0.7000")}
    assert other_id not in effective_price_factors(db_conn, MONDAY)


def test_promo_day_discounts_one_store_and_sells_more_units(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _parameters(db_conn)
    product_id = insert_product(db_conn, name="Молоко", retail_price=RETAIL_PRICE)
    promo_store_id, promo_location_id = _store(db_conn, "Акция")
    plain_store_id, plain_location_id = _store(db_conn, "Обычный")
    _assortment(db_conn, promo_store_id, product_id)
    _assortment(db_conn, plain_store_id, product_id)
    stock = DayStock(
        {
            (promo_location_id, product_id): STOCK_QTY,
            (plain_location_id, product_id): STOCK_QTY,
        }
    )

    run_sales(db_conn, MONDAY, stock, SEED)
    baseline = _lines(db_conn)
    baseline_promo_units = _units(baseline, promo_store_id)
    baseline_plain = _signature(baseline, plain_store_id)
    assert baseline_promo_units > 0
    assert baseline_plain

    insert_sale_period(db_conn, MONDAY, MONDAY, Decimal("0.8"), [promo_store_id])
    run_sales(db_conn, MONDAY, stock, SEED)
    promo_lines = _lines(db_conn)

    assert _units(promo_lines, promo_store_id) > baseline_promo_units
    assert _signature(promo_lines, plain_store_id) == baseline_plain
    promo_rows = [row for row in promo_lines if row[0] == promo_store_id]
    assert promo_rows
    for _store_id, _ts, line_product_id, _quantity, price, discount, clearance in promo_rows:
        assert line_product_id == product_id
        assert price == Decimal("80.00")
        assert discount == Decimal("20.00")
        assert clearance == 1
    for row in baseline:
        if row[0] == promo_store_id:
            assert row[4] == RETAIL_PRICE
            assert row[5] == 0
            assert row[6] == 0

    again = run_sales(db_conn, MONDAY, stock, SEED)
    replaced = _lines(db_conn)
    assert replaced == promo_lines
    assert again.units_sold == _units(replaced, promo_store_id) + _units(replaced, plain_store_id)
