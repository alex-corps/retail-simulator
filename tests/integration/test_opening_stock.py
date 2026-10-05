from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from psycopg import Connection

from retail_sim.core.stock import NegativeStockError, StockKey
from retail_sim.steps.s0_opening_stock import run_opening_stock
from tests.integration.helpers import insert_product, insert_storage_location

DAY = date(2026, 10, 5)


def _reset_stock_tables(conn: Connection[Any]) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM inventory_movements")
        cur.execute("DELETE FROM daily_opening_stock")


def _insert_movement(
    conn: Connection[Any],
    *,
    op_day: date,
    product_id: int,
    storage_location_id: int,
    quantity: int,
) -> None:
    op_type = "приход" if quantity > 0 else "продажа"
    sender_location_id = None if quantity > 0 else storage_location_id
    receiver_location_id = storage_location_id if quantity > 0 else None
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
                datetime.combine(op_day, datetime.min.time()).replace(hour=12),
                product_id,
                storage_location_id,
                sender_location_id,
                receiver_location_id,
                quantity,
                op_type,
            ),
        )


def _insert_snapshot(
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


def _snapshot_quantity(
    conn: Connection[Any],
    stock_date: date,
    storage_location_id: int,
    product_id: int,
) -> int | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT quantity
            FROM daily_opening_stock
            WHERE stock_date = %s
              AND storage_location_id = %s
              AND product_id = %s
            """,
            (stock_date, storage_location_id, product_id),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return int(row[0])


def _snapshot_dates(conn: Connection[Any]) -> set[date]:
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT stock_date FROM daily_opening_stock")
        return {row[0] for row in cur.fetchall()}


def _seed_key(conn: Connection[Any]) -> StockKey:
    location_id = insert_storage_location(conn, "склад")
    product_id = insert_product(conn, name=f"sku-{location_id}")
    return location_id, product_id


def test_cold_start_without_history_writes_no_snapshot(db_conn: Connection[Any]) -> None:
    _reset_stock_tables(db_conn)
    key = _seed_key(db_conn)

    stock = run_opening_stock(db_conn, DAY)

    assert stock.opening(key) == 0
    assert stock.current(key) == 0
    assert _snapshot_dates(db_conn) == set()


def test_opening_is_previous_snapshot_plus_previous_day_movements(
    db_conn: Connection[Any],
) -> None:
    _reset_stock_tables(db_conn)
    key = _seed_key(db_conn)
    location_id, product_id = key
    previous_day = DAY - timedelta(days=1)
    _insert_snapshot(db_conn, previous_day, location_id, product_id, 10)
    _insert_movement(
        db_conn,
        op_day=DAY - timedelta(days=5),
        product_id=product_id,
        storage_location_id=location_id,
        quantity=100,
    )
    _insert_movement(
        db_conn,
        op_day=previous_day,
        product_id=product_id,
        storage_location_id=location_id,
        quantity=5,
    )
    _insert_movement(
        db_conn,
        op_day=DAY,
        product_id=product_id,
        storage_location_id=location_id,
        quantity=-3,
    )

    stock = run_opening_stock(db_conn, DAY)

    assert stock.opening(key) == 15
    assert stock.current(key) == 12
    assert _snapshot_quantity(db_conn, DAY, location_id, product_id) == 15


def test_gap_uses_earlier_snapshot_plus_movements_through_previous_day(
    db_conn: Connection[Any],
) -> None:
    _reset_stock_tables(db_conn)
    key = _seed_key(db_conn)
    location_id, product_id = key
    _insert_snapshot(db_conn, DAY - timedelta(days=5), location_id, product_id, 10)
    _insert_movement(
        db_conn,
        op_day=DAY - timedelta(days=3),
        product_id=product_id,
        storage_location_id=location_id,
        quantity=-4,
    )

    stock = run_opening_stock(db_conn, DAY)

    assert stock.opening(key) == 6
    assert _snapshot_quantity(db_conn, DAY, location_id, product_id) == 6


def test_missing_zero_snapshot_falls_back_to_earlier_snapshot(
    db_conn: Connection[Any],
) -> None:
    _reset_stock_tables(db_conn)
    key = _seed_key(db_conn)
    location_id, product_id = key
    _insert_snapshot(db_conn, DAY - timedelta(days=5), location_id, product_id, 10)
    _insert_movement(
        db_conn,
        op_day=DAY - timedelta(days=4),
        product_id=product_id,
        storage_location_id=location_id,
        quantity=-10,
    )
    _insert_movement(
        db_conn,
        op_day=DAY - timedelta(days=2),
        product_id=product_id,
        storage_location_id=location_id,
        quantity=2,
    )

    stock = run_opening_stock(db_conn, DAY)

    assert stock.opening(key) == 2
    assert _snapshot_quantity(db_conn, DAY, location_id, product_id) == 2


def test_existing_snapshot_for_day_is_recomputed(db_conn: Connection[Any]) -> None:
    _reset_stock_tables(db_conn)
    key = _seed_key(db_conn)
    location_id, product_id = key
    previous_day = DAY - timedelta(days=1)
    _insert_snapshot(db_conn, DAY, location_id, product_id, 100)
    _insert_snapshot(db_conn, previous_day, location_id, product_id, 10)
    _insert_movement(
        db_conn,
        op_day=previous_day,
        product_id=product_id,
        storage_location_id=location_id,
        quantity=1,
    )

    first = run_opening_stock(db_conn, DAY)
    second = run_opening_stock(db_conn, DAY)

    assert first.opening(key) == 11
    assert second.opening(key) == 11
    assert _snapshot_quantity(db_conn, DAY, location_id, product_id) == 11


def test_old_snapshots_are_pruned(db_conn: Connection[Any]) -> None:
    _reset_stock_tables(db_conn)
    location_id, product_id = _seed_key(db_conn)
    keep = {
        DAY - timedelta(days=21),
        DAY - timedelta(days=28),
        date(2026, 9, 1),
        date(2026, 7, 1),
        DAY - timedelta(days=70),
    }
    drop = {
        DAY - timedelta(days=22),
        date(2026, 9, 2),
        DAY - timedelta(days=71),
    }
    _insert_snapshot(db_conn, DAY - timedelta(days=21), location_id, product_id, 7)
    for stock_date in (keep | drop) - {DAY - timedelta(days=21)}:
        _insert_snapshot(db_conn, stock_date, location_id, product_id, 1)

    stock = run_opening_stock(db_conn, DAY)

    assert stock.opening((location_id, product_id)) == 7
    assert _snapshot_dates(db_conn) == keep | {DAY}
    assert _snapshot_quantity(db_conn, DAY, location_id, product_id) == 7


def test_negative_opening_stock_raises(db_conn: Connection[Any]) -> None:
    _reset_stock_tables(db_conn)
    location_id, product_id = _seed_key(db_conn)
    previous_day = DAY - timedelta(days=1)
    _insert_snapshot(db_conn, previous_day, location_id, product_id, 5)
    _insert_movement(
        db_conn,
        op_day=previous_day,
        product_id=product_id,
        storage_location_id=location_id,
        quantity=-8,
    )

    with pytest.raises(NegativeStockError):
        run_opening_stock(db_conn, DAY)

    assert _snapshot_quantity(db_conn, DAY, location_id, product_id) is None
    assert _snapshot_quantity(db_conn, previous_day, location_id, product_id) == 5


def test_day_stock_includes_movements_of_the_calculated_day(db_conn: Connection[Any]) -> None:
    _reset_stock_tables(db_conn)
    key = _seed_key(db_conn)
    location_id, product_id = key
    _insert_movement(
        db_conn,
        op_day=DAY,
        product_id=product_id,
        storage_location_id=location_id,
        quantity=4,
    )

    stock = run_opening_stock(db_conn, DAY)

    assert stock.opening(key) == 0
    assert stock.current(key) == 4
    assert stock.positive_keys() == [key]
    assert _snapshot_quantity(db_conn, DAY, location_id, product_id) is None
