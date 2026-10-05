from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import date

    from psycopg import Connection

    from retail_sim.core.stock import StockKey


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
