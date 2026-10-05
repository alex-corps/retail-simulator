from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from retail_sim.db.copy import copy_rows

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime

    from psycopg import Connection

    from retail_sim.core.stock import StockKey
    from retail_sim.domain.enums import OperationType

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
