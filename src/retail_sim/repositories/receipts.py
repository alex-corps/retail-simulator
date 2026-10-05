from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from retail_sim.db.copy import copy_rows

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date, datetime
    from decimal import Decimal

    from psycopg import Connection

_RECEIPT_COLUMNS = ("id", "store_id", "receipt_ts")
_LINE_COLUMNS = (
    "receipt_id",
    "product_id",
    "quantity",
    "sale_price",
    "discount_pct",
    "clearance_flag",
)


def reserve_receipt_ids(conn: Connection[Any], count: int) -> list[int]:
    # COPY не возвращает id. Строки чека ссылаются на заранее занятый id.
    if count <= 0:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT nextval(pg_get_serial_sequence('receipts', 'id'))
            FROM generate_series(1, %(count)s)
            """,
            {"count": count},
        )
        return [int(row[0]) for row in cur.fetchall()]


def insert_receipts(
    conn: Connection[Any],
    rows: Sequence[tuple[int, int, datetime]],
) -> int:
    return copy_rows(conn, "receipts", _RECEIPT_COLUMNS, rows)


def insert_receipt_lines(
    conn: Connection[Any],
    rows: Sequence[tuple[int, int, int, Decimal, Decimal, int]],
) -> int:
    return copy_rows(conn, "receipt_lines", _LINE_COLUMNS, rows)


def delete_day_receipts(conn: Connection[Any], day: date) -> int:
    next_day = day + timedelta(days=1)
    params = {"day": day, "next_day": next_day}
    with conn.cursor() as cur:
        # Строки ссылаются на чек, поэтому удаляем их первыми.
        cur.execute(
            """
            DELETE FROM receipt_lines AS lines
            USING receipts
            WHERE lines.receipt_id = receipts.id
              AND receipts.receipt_ts >= %(day)s
              AND receipts.receipt_ts < %(next_day)s
            """,
            params,
        )
        cur.execute(
            """
            DELETE FROM receipts
            WHERE receipt_ts >= %(day)s
              AND receipt_ts < %(next_day)s
            """,
            params,
        )
        return int(cur.rowcount)
