from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import psycopg
import pytest
from psycopg import Connection

from retail_sim.domain.enums import LocationType, OperationType, OptimizationFlag
from tests.conftest import is_db_reachable
from tests.integration.helpers import (
    insert_calculation_parameters,
    insert_product,
    insert_storage_location,
    insert_warehouse,
)

EXPECTED_TABLES = {
    "storage_locations",
    "products",
    "warehouses",
    "stores",
    "store_name_pool",
    "calculation_parameters",
    "store_assortment",
    "daily_opening_stock",
    "inventory_movements",
    "receipts",
    "receipt_lines",
}

EXPECTED_INDEXES = {
    "idx_products_category_l2",
    "idx_inventory_movements_op_date_location_product",
    "idx_receipts_store_ts",
}

pytestmark = pytest.mark.skipif(
    not is_db_reachable(),
    reason="PostgreSQL is not reachable",
)


def _constraint_def(conn: Connection[Any], name: str) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = %s",
            (name,),
        )
        row = cur.fetchone()
        assert row is not None
        return str(row[0])


def test_tables_exist(db_conn: Connection[Any]) -> None:
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """
        )
        names = {str(row[0]) for row in cur.fetchall()}
    assert names >= EXPECTED_TABLES


def test_indexes_exist(db_conn: Connection[Any]) -> None:
    with db_conn.cursor() as cur:
        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        names = {str(row[0]) for row in cur.fetchall()}
    assert names >= EXPECTED_INDEXES


def test_check_constraints_match_enums(db_conn: Connection[Any]) -> None:
    location_def = _constraint_def(db_conn, "storage_locations_location_type_check")
    for location in LocationType:
        assert location.value in location_def

    operation_def = _constraint_def(db_conn, "inventory_movements_op_type_check")
    for operation in OperationType:
        assert operation.value in operation_def

    flag_def = _constraint_def(db_conn, "stores_optimization_flag_check")
    compact_flag_def = "".join(flag_def.split())
    for flag in OptimizationFlag:
        assert str(int(flag)) in compact_flag_def


def _expect_violation(
    conn: Connection[Any],
    error: type[psycopg.Error],
    sql: str,
    params: tuple[Any, ...] = (),
) -> None:
    with conn.cursor() as cur, pytest.raises(error), conn.transaction():
        cur.execute(sql, params)


def test_calculation_parameters_rejects_second_row(db_conn: Connection[Any]) -> None:
    insert_calculation_parameters(db_conn)
    _expect_violation(
        db_conn,
        psycopg.errors.CheckViolation,
        """
        INSERT INTO calculation_parameters (
            id,
            avg_receipts_per_day,
            avg_receipt_amount,
            avg_sku_capacity,
            min_receipt_amount,
            max_receipt_amount,
            target_stock_days_warehouse,
            target_stock_days_store
        ) VALUES (2, 1, 1, 1, 1, 2, 1, 1)
        """,
    )


def test_rejects_bad_location_type(db_conn: Connection[Any]) -> None:
    _expect_violation(
        db_conn,
        psycopg.errors.CheckViolation,
        "INSERT INTO storage_locations (location_type) VALUES (%s)",
        ("офис",),
    )


def test_rejects_bad_op_type(db_conn: Connection[Any]) -> None:
    location_id = insert_storage_location(db_conn, "склад")
    product_id = insert_product(db_conn)
    _expect_violation(
        db_conn,
        psycopg.errors.CheckViolation,
        """
        INSERT INTO inventory_movements (
            op_ts, product_id, storage_location_id, quantity, op_type
        ) VALUES (%s, %s, %s, %s, %s)
        """,
        (datetime(2026, 3, 15, 12, 0), product_id, location_id, 1, "нет"),
    )


def test_rejects_bad_optimization_flag(db_conn: Connection[Any]) -> None:
    warehouse_location_id = insert_storage_location(db_conn, "склад")
    warehouse_id = insert_warehouse(db_conn, warehouse_location_id, "Main")
    store_location_id = insert_storage_location(db_conn, "магазин")
    _expect_violation(
        db_conn,
        psycopg.errors.CheckViolation,
        """
        INSERT INTO stores (
            storage_location_id, warehouse_id, name, avg_receipts_per_day,
            sku_capacity, open_from, open_to, optimization_flag
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            store_location_id,
            warehouse_id,
            "North",
            "100.00",
            10,
            time(10, 0),
            time(21, 0),
            9,
        ),
    )


def test_rejects_duplicate_store_name(db_conn: Connection[Any]) -> None:
    warehouse_location_id = insert_storage_location(db_conn, "склад")
    warehouse_id = insert_warehouse(db_conn, warehouse_location_id, "Main")
    first_location_id = insert_storage_location(db_conn, "магазин")
    second_location_id = insert_storage_location(db_conn, "магазин")
    with db_conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO stores (
                storage_location_id, warehouse_id, name, avg_receipts_per_day,
                sku_capacity, open_from, open_to
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (first_location_id, warehouse_id, "North", "100.00", 10, time(10, 0), time(21, 0)),
        )
        with pytest.raises(psycopg.errors.UniqueViolation), db_conn.transaction():
            cur.execute(
                """
                INSERT INTO stores (
                    storage_location_id, warehouse_id, name, avg_receipts_per_day,
                    sku_capacity, open_from, open_to
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    second_location_id,
                    warehouse_id,
                    "North",
                    "100.00",
                    10,
                    time(10, 0),
                    time(21, 0),
                ),
            )


def test_rejects_zero_movement_quantity(db_conn: Connection[Any]) -> None:
    location_id = insert_storage_location(db_conn, "склад")
    product_id = insert_product(db_conn)
    _expect_violation(
        db_conn,
        psycopg.errors.CheckViolation,
        """
        INSERT INTO inventory_movements (
            op_ts, product_id, storage_location_id, quantity, op_type
        ) VALUES (%s, %s, %s, %s, %s)
        """,
        (datetime(2026, 3, 15, 12, 0), product_id, location_id, 0, "приход"),
    )


def test_rejects_open_from_not_before_open_to(db_conn: Connection[Any]) -> None:
    warehouse_location_id = insert_storage_location(db_conn, "склад")
    warehouse_id = insert_warehouse(db_conn, warehouse_location_id, "Main")
    store_location_id = insert_storage_location(db_conn, "магазин")
    _expect_violation(
        db_conn,
        psycopg.errors.CheckViolation,
        """
        INSERT INTO stores (
            storage_location_id, warehouse_id, name, avg_receipts_per_day,
            sku_capacity, open_from, open_to
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            store_location_id,
            warehouse_id,
            "North",
            "100.00",
            10,
            time(21, 0),
            time(10, 0),
        ),
    )


def test_rejects_store_with_missing_warehouse(db_conn: Connection[Any]) -> None:
    store_location_id = insert_storage_location(db_conn, "магазин")
    _expect_violation(
        db_conn,
        psycopg.errors.ForeignKeyViolation,
        """
        INSERT INTO stores (
            storage_location_id, warehouse_id, name, avg_receipts_per_day,
            sku_capacity, open_from, open_to
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (store_location_id, 999_999_999, "North", "100.00", 10, time(10, 0), time(21, 0)),
    )


def test_op_date_is_generated_from_op_ts(db_conn: Connection[Any]) -> None:
    location_id = insert_storage_location(db_conn, "склад")
    product_id = insert_product(db_conn)
    with db_conn.cursor() as cur:
        cur.execute(
            """
            SELECT is_generated
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'inventory_movements'
              AND column_name = 'op_date'
            """
        )
        generated = cur.fetchone()
        assert generated is not None
        assert generated[0] == "ALWAYS"

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
            ) VALUES (%s, %s, %s, NULL, %s, %s, %s)
            RETURNING op_date
            """,
            (datetime(2026, 3, 15, 14, 30), product_id, location_id, location_id, 1000, "приход"),
        )
        row = cur.fetchone()
    assert row is not None
    assert row[0] == date(2026, 3, 15)
