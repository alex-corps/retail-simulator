from __future__ import annotations

from datetime import time
from decimal import Decimal
from typing import Any

from psycopg import Connection


def insert_storage_location(conn: Connection[Any], location_type: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO storage_locations (location_type) VALUES (%s) RETURNING id",
            (location_type,),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def insert_product(
    conn: Connection[Any],
    *,
    category_l1: str = "Продукты",
    category_l2: str = "Молоко",
    name: str = "Молоко 1л",
    purchase_price: Decimal = Decimal("40.00"),
    retail_price: Decimal = Decimal("59.90"),
    avg_daily_sales: Decimal = Decimal("3.50"),
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO products (
                category_l1, category_l2, name, purchase_price, retail_price, avg_daily_sales
            ) VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (category_l1, category_l2, name, purchase_price, retail_price, avg_daily_sales),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def insert_warehouse(conn: Connection[Any], storage_location_id: int, name: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO warehouses (storage_location_id, name)
            VALUES (%s, %s)
            RETURNING id
            """,
            (storage_location_id, name),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def insert_store(
    conn: Connection[Any],
    *,
    storage_location_id: int,
    warehouse_id: int,
    name: str,
    avg_receipts_per_day: Decimal = Decimal("120.00"),
    sku_capacity: int = 800,
    open_from: time = time(10, 0),
    open_to: time = time(21, 0),
    optimization_flag: int = 0,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO stores (
                storage_location_id,
                warehouse_id,
                name,
                avg_receipts_per_day,
                sku_capacity,
                open_from,
                open_to,
                optimization_flag
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                storage_location_id,
                warehouse_id,
                name,
                avg_receipts_per_day,
                sku_capacity,
                open_from,
                open_to,
                optimization_flag,
            ),
        )
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def insert_calculation_parameters(conn: Connection[Any]) -> None:
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
                7,
            ),
        )
