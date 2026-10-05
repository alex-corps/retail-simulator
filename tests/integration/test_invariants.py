from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

import pytest
from psycopg import Connection

from retail_sim.simulation.invariants import (
    RULE_NON_NEGATIVE_STOCK,
    RULE_OPERATION_LOCATION,
    RULE_RECEIPT_HAS_LINES,
    RULE_RECEIPT_HOURS,
    RULE_SALE_IN_ASSORTMENT,
    RULE_SALES_MATCH_RECEIPTS,
    RULE_TRANSFER_BALANCE,
    InvariantError,
    check_day_invariants,
)
from tests.integration.helpers import (
    insert_product,
    insert_storage_location,
    insert_store,
    insert_warehouse,
)

DAY = date(2026, 6, 1)
AT_NOON = datetime(2026, 6, 1, 12, 0)
BEFORE_OPEN = datetime(2026, 6, 1, 8, 0)


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


def _store(conn: Connection[Any]) -> tuple[int, int, int]:
    warehouse_location_id = insert_storage_location(conn, "склад")
    warehouse_id = insert_warehouse(conn, warehouse_location_id, "Склад")
    store_location_id = insert_storage_location(conn, "магазин")
    store_id = insert_store(
        conn,
        storage_location_id=store_location_id,
        warehouse_id=warehouse_id,
        name="Магазин",
        open_from=time(10, 0),
        open_to=time(21, 0),
    )
    product_id = insert_product(conn, name="Milk", retail_price=Decimal("80.00"))
    return store_id, store_location_id, product_id


def _opening(conn: Connection[Any], location_id: int, product_id: int, quantity: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO daily_opening_stock (
                stock_date, storage_location_id, product_id, quantity
            ) VALUES (%s, %s, %s, %s)
            """,
            (DAY, location_id, product_id, quantity),
        )


def _assortment(conn: Connection[Any], store_id: int, product_id: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO store_assortment (store_id, product_id, avg_daily_sales)
            VALUES (%s, %s, %s)
            """,
            (store_id, product_id, Decimal("2.00")),
        )


def _movement(
    conn: Connection[Any],
    *,
    product_id: int,
    location_id: int,
    quantity: int,
    op_type: str,
    sender_location_id: int | None,
    receiver_location_id: int | None,
    op_ts: datetime = AT_NOON,
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
                op_ts,
                product_id,
                location_id,
                sender_location_id,
                receiver_location_id,
                quantity,
                op_type,
            ),
        )


def _receipt(conn: Connection[Any], store_id: int, receipt_ts: datetime) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO receipts (store_id, receipt_ts)
            VALUES (%s, %s)
            RETURNING id
            """,
            (store_id, receipt_ts),
        )
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _line(conn: Connection[Any], receipt_id: int, product_id: int, quantity: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO receipt_lines (receipt_id, product_id, quantity, sale_price)
            VALUES (%s, %s, %s, %s)
            """,
            (receipt_id, product_id, quantity, Decimal("80.00")),
        )


def _expect(conn: Connection[Any], rule: str) -> None:
    with pytest.raises(InvariantError) as caught:
        check_day_invariants(conn, DAY)
    assert caught.value.rule == rule
    assert caught.value.details


def test_consistent_day_passes(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    store_id, location_id, product_id = _store(db_conn)
    _opening(db_conn, location_id, product_id, 10)
    _assortment(db_conn, store_id, product_id)
    receipt_id = _receipt(db_conn, store_id, AT_NOON)
    _line(db_conn, receipt_id, product_id, 1)
    _movement(
        db_conn,
        product_id=product_id,
        location_id=location_id,
        quantity=-1,
        op_type="продажа",
        sender_location_id=location_id,
        receiver_location_id=None,
    )

    check_day_invariants(db_conn, DAY)


def test_negative_stock_fails(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _store_id, location_id, product_id = _store(db_conn)
    _opening(db_conn, location_id, product_id, 1)
    _movement(
        db_conn,
        product_id=product_id,
        location_id=location_id,
        quantity=-5,
        op_type="продажа",
        sender_location_id=location_id,
        receiver_location_id=None,
    )

    _expect(db_conn, RULE_NON_NEGATIVE_STOCK)


def test_unbalanced_transfer_fails(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _store_id, location_id, product_id = _store(db_conn)
    _opening(db_conn, location_id, product_id, 10)
    _movement(
        db_conn,
        product_id=product_id,
        location_id=location_id,
        quantity=-3,
        op_type="перемещение",
        sender_location_id=location_id,
        receiver_location_id=location_id,
    )

    _expect(db_conn, RULE_TRANSFER_BALANCE)


def test_receipt_onto_a_store_fails(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _store_id, location_id, product_id = _store(db_conn)
    _movement(
        db_conn,
        product_id=product_id,
        location_id=location_id,
        quantity=1,
        op_type="приход",
        sender_location_id=None,
        receiver_location_id=location_id,
    )

    _expect(db_conn, RULE_OPERATION_LOCATION)


def test_sale_without_a_receipt_fails(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    _store_id, location_id, product_id = _store(db_conn)
    _opening(db_conn, location_id, product_id, 10)
    _movement(
        db_conn,
        product_id=product_id,
        location_id=location_id,
        quantity=-1,
        op_type="продажа",
        sender_location_id=location_id,
        receiver_location_id=None,
    )

    _expect(db_conn, RULE_SALES_MATCH_RECEIPTS)


def test_receipt_without_lines_fails(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    store_id, _location_id, _product_id = _store(db_conn)
    _receipt(db_conn, store_id, AT_NOON)

    _expect(db_conn, RULE_RECEIPT_HAS_LINES)


def test_receipt_outside_opening_hours_fails(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    store_id, location_id, product_id = _store(db_conn)
    _opening(db_conn, location_id, product_id, 10)
    _assortment(db_conn, store_id, product_id)
    receipt_id = _receipt(db_conn, store_id, BEFORE_OPEN)
    _line(db_conn, receipt_id, product_id, 1)
    _movement(
        db_conn,
        product_id=product_id,
        location_id=location_id,
        quantity=-1,
        op_type="продажа",
        sender_location_id=location_id,
        receiver_location_id=None,
        op_ts=BEFORE_OPEN,
    )

    _expect(db_conn, RULE_RECEIPT_HOURS)


def test_sale_outside_assortment_fails(db_conn: Connection[Any]) -> None:
    _isolate(db_conn)
    store_id, location_id, _listed = _store(db_conn)
    outsider = insert_product(conn=db_conn, name="Soap", retail_price=Decimal("30.00"))
    _opening(db_conn, location_id, outsider, 5)
    receipt_id = _receipt(db_conn, store_id, AT_NOON)
    _line(db_conn, receipt_id, outsider, 1)
    _movement(
        db_conn,
        product_id=outsider,
        location_id=location_id,
        quantity=-1,
        op_type="продажа",
        sender_location_id=location_id,
        receiver_location_id=None,
    )

    _expect(db_conn, RULE_SALE_IN_ASSORTMENT)
