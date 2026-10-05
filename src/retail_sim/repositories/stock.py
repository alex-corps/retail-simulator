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


def positive_stock_days(
    conn: Connection[Any],
    location_ids: Sequence[int],
    date_from: date,
    date_to: date,
) -> dict[StockKey, set[date]]:
    # Дни, в которые остаток на начало дня был больше нуля. Нулевые снимки не считаются.
    if not location_ids or date_from > date_to:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT storage_location_id, product_id, stock_date
            FROM daily_opening_stock
            WHERE stock_date BETWEEN %(date_from)s AND %(date_to)s
              AND quantity > 0
              AND storage_location_id = ANY(%(location_ids)s)
            """,
            {
                "location_ids": list(location_ids),
                "date_from": date_from,
                "date_to": date_to,
            },
        )
        rows = cur.fetchall()
    days: dict[StockKey, set[date]] = {}
    for location_id, product_id, stock_date in rows:
        key = (int(location_id), int(product_id))
        days.setdefault(key, set()).add(cast("date", stock_date))
    return days
