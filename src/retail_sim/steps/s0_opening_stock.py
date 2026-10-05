from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from retail_sim.core.retention import dates_to_prune
from retail_sim.core.stock import DayStock, compute_opening_stock
from retail_sim.repositories.movements import sum_movements
from retail_sim.repositories.stock import (
    delete_snapshots,
    get_latest_snapshot_date_before,
    insert_snapshot,
    list_snapshot_dates,
    load_snapshot,
)

if TYPE_CHECKING:
    from datetime import date

    from psycopg import Connection


def run_opening_stock(conn: Connection[Any], day: date) -> DayStock:
    delete_snapshots(conn, [day])
    base_date = get_latest_snapshot_date_before(conn, day)
    base = load_snapshot(conn, base_date) if base_date is not None else {}
    previous_day = day - timedelta(days=1)
    deltas = sum_movements(conn, base_date, previous_day)
    opening = compute_opening_stock(base, deltas)
    insert_snapshot(conn, day, opening)
    delete_snapshots(conn, dates_to_prune(list_snapshot_dates(conn), day))
    today_deltas = sum_movements(conn, day, day)
    return DayStock(opening, today_deltas)
