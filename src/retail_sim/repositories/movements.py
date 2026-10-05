from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from retail_sim.db.copy import copy_rows
from retail_sim.domain.enums import OperationType

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime

    from psycopg import Connection

    from retail_sim.core.stock import StockKey

_MOVEMENT_COLUMNS = (
    "op_ts",
    "product_id",
    "storage_location_id",
    "sender_location_id",
    "receiver_location_id",
    "quantity",
    "op_type",
)


@dataclass(frozen=True, slots=True)
class MovementDraft:
    op_ts: datetime
    product_id: int
    storage_location_id: int
    sender_location_id: int | None
    receiver_location_id: int | None
    quantity: int
    op_type: OperationType


def sum_movements(
    conn: Connection[Any],
    date_from: date | None,
    date_to: date,
) -> dict[StockKey, int]:
    if date_from is not None and date_from > date_to:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT storage_location_id, product_id, SUM(quantity)::bigint
            FROM inventory_movements
            WHERE op_date <= %(date_to)s
              AND (%(date_from)s::date IS NULL OR op_date >= %(date_from)s)
            GROUP BY storage_location_id, product_id
            HAVING SUM(quantity) <> 0
            """,
            {"date_from": date_from, "date_to": date_to},
        )
        rows = cur.fetchall()
    return {
        (int(location_id), int(product_id)): int(quantity)
        for location_id, product_id, quantity in rows
    }


def insert_movements(conn: Connection[Any], rows: Sequence[MovementDraft]) -> int:
    if not rows:
        return 0
    payload = [
        (
            row.op_ts,
            row.product_id,
            row.storage_location_id,
            row.sender_location_id,
            row.receiver_location_id,
            row.quantity,
            str(row.op_type),
        )
        for row in rows
    ]
    return copy_rows(conn, "inventory_movements", _MOVEMENT_COLUMNS, payload)


def has_any_movements(conn: Connection[Any]) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM inventory_movements)")
        row = cur.fetchone()
    return row is not None and bool(row[0])


def delete_receipts(
    conn: Connection[Any],
    day: date,
    location_ids: Sequence[int],
) -> dict[StockKey, int]:
    # Снимаем приход поставщика за день, чтобы повторный расчёт не задвоил поставку.
    if not location_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM inventory_movements
            WHERE op_date = %(day)s
              AND op_type = %(op_type)s
              AND storage_location_id = ANY(%(location_ids)s)
            RETURNING storage_location_id, product_id, quantity
            """,
            {
                "day": day,
                "op_type": str(OperationType.RECEIPT),
                "location_ids": list(location_ids),
            },
        )
        rows = cur.fetchall()
    removed: dict[StockKey, int] = {}
    for location_id, product_id, quantity in rows:
        key = (int(location_id), int(product_id))
        removed[key] = removed.get(key, 0) + int(quantity)
    return removed


def delete_sales(
    conn: Connection[Any],
    day: date,
    location_ids: Sequence[int],
) -> dict[StockKey, int]:
    # Снимаем продажи за день, чтобы повторный расчёт не задвоил списание.
    if not location_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM inventory_movements
            WHERE op_date = %(day)s
              AND op_type = %(op_type)s
              AND storage_location_id = ANY(%(location_ids)s)
            RETURNING storage_location_id, product_id, quantity
            """,
            {
                "day": day,
                "op_type": str(OperationType.SALE),
                "location_ids": list(location_ids),
            },
        )
        rows = cur.fetchall()
    removed: dict[StockKey, int] = {}
    for location_id, product_id, quantity in rows:
        key = (int(location_id), int(product_id))
        removed[key] = removed.get(key, 0) + int(quantity)
    return removed


def delete_store_replenishments(
    conn: Connection[Any],
    day: date,
    warehouse_location_ids: Sequence[int],
) -> dict[StockKey, int]:
    # Отгрузка в магазин идёт из склада. Возврат (отправитель — магазин) не трогаем.
    if not warehouse_location_ids:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM inventory_movements
            WHERE op_date = %(day)s
              AND op_type = %(op_type)s
              AND sender_location_id = ANY(%(warehouse_location_ids)s)
            RETURNING storage_location_id, product_id, quantity
            """,
            {
                "day": day,
                "op_type": str(OperationType.TRANSFER),
                "warehouse_location_ids": list(warehouse_location_ids),
            },
        )
        rows = cur.fetchall()
    removed: dict[StockKey, int] = {}
    for location_id, product_id, quantity in rows:
        key = (int(location_id), int(product_id))
        removed[key] = removed.get(key, 0) + int(quantity)
    return removed


def daily_outflow(
    conn: Connection[Any],
    location_ids: Sequence[int],
    op_type: OperationType,
    date_from: date,
    date_to: date,
) -> dict[StockKey, dict[date, int]]:
    # Расход — только исходящие строки: приход на это место и возвраты не входят.
    if not location_ids or date_from > date_to:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT storage_location_id, product_id, op_date, SUM(-quantity)::bigint
            FROM inventory_movements
            WHERE op_date BETWEEN %(date_from)s AND %(date_to)s
              AND op_type = %(op_type)s
              AND quantity < 0
              AND storage_location_id = ANY(%(location_ids)s)
            GROUP BY storage_location_id, product_id, op_date
            HAVING SUM(-quantity) <> 0
            """,
            {
                "location_ids": list(location_ids),
                "op_type": str(op_type),
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        rows = cur.fetchall()
    outflow: dict[StockKey, dict[date, int]] = {}
    for location_id, product_id, op_date, quantity in rows:
        key = (int(location_id), int(product_id))
        outflow.setdefault(key, {})[cast("date", op_date)] = int(quantity)
    return outflow
