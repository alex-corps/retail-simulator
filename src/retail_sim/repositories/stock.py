from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from retail_sim.db.copy import copy_rows

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from datetime import date

    from psycopg import Connection

    from retail_sim.core.stock import StockKey

_SNAPSHOT_COLUMNS = (
    "stock_date",
    "storage_location_id",
    "product_id",
    "quantity",
)


def get_latest_snapshot_date_before(conn: Connection[Any], day: date) -> date | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT MAX(stock_date)
            FROM daily_opening_stock
            WHERE stock_date < %s
            """,
            (day,),
        )
        row = cur.fetchone()
    if row is None or row[0] is None:
        return None
    return cast("date", row[0])


def load_snapshot(conn: Connection[Any], day: date) -> dict[StockKey, int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT storage_location_id, product_id, quantity
            FROM daily_opening_stock
            WHERE stock_date = %s
            """,
            (day,),
        )
        rows = cur.fetchall()
    return {
        (int(location_id), int(product_id)): int(quantity)
        for location_id, product_id, quantity in rows
    }


def list_snapshot_dates(conn: Connection[Any]) -> list[date]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT stock_date
            FROM daily_opening_stock
            ORDER BY stock_date
            """
        )
        return [cast("date", row[0]) for row in cur.fetchall()]


def delete_snapshots(conn: Connection[Any], dates: Sequence[date]) -> None:
    if not dates:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM daily_opening_stock
            WHERE stock_date = ANY(%s)
            """,
            (list(dates),),
        )


def insert_snapshot(conn: Connection[Any], day: date, stock: Mapping[StockKey, int]) -> None:
    rows = [
        (day, location_id, product_id, quantity)
        for (location_id, product_id), quantity in sorted(stock.items())
        if quantity != 0
    ]
    if not rows:
        return
    copy_rows(conn, "daily_opening_stock", _SNAPSHOT_COLUMNS, rows)
