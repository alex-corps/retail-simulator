from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from psycopg.rows import class_row

from retail_sim.domain.enums import OptimizationFlag
from retail_sim.domain.models import Store, StoreAssortmentItem

if TYPE_CHECKING:
    from psycopg import Connection

_STORE_COLUMNS = """
    id,
    storage_location_id,
    warehouse_id,
    name,
    avg_receipts_per_day,
    sku_capacity,
    open_from,
    open_to,
    optimization_flag
"""


def _as_store(row: Store) -> Store:
    return replace(row, optimization_flag=OptimizationFlag(int(row.optimization_flag)))


def _fetch_stores(
    conn: Connection[Any],
    where_sql: str,
    params: tuple[Any, ...],
) -> list[Store]:
    with conn.cursor(row_factory=class_row(Store)) as cur:
        cur.execute(
            f"""
            SELECT {_STORE_COLUMNS}
            FROM stores
            {where_sql}
            ORDER BY id
            """,
            params,
        )
        rows = cur.fetchall()
    return [_as_store(row) for row in rows]


def list_stores(conn: Connection[Any]) -> list[Store]:
    return _fetch_stores(conn, "", ())


def get_store(conn: Connection[Any], store_id: int) -> Store | None:
    rows = _fetch_stores(conn, "WHERE id = %s", (store_id,))
    if not rows:
        return None
    return rows[0]


def list_stores_by_flag(conn: Connection[Any], flag: OptimizationFlag) -> list[Store]:
    return _fetch_stores(conn, "WHERE optimization_flag = %s", (int(flag),))


def list_unused_store_names(conn: Connection[Any]) -> list[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT pool.name
            FROM store_name_pool AS pool
            WHERE NOT EXISTS (
                SELECT 1
                FROM stores
                WHERE stores.name = pool.name
            )
            ORDER BY pool.name
            """
        )
        return [str(row[0]) for row in cur.fetchall()]


def list_store_assortment(conn: Connection[Any], store_id: int) -> list[StoreAssortmentItem]:
    with conn.cursor(row_factory=class_row(StoreAssortmentItem)) as cur:
        cur.execute(
            """
            SELECT store_id, product_id, avg_daily_sales
            FROM store_assortment
            WHERE store_id = %s
            ORDER BY product_id
            """,
            (store_id,),
        )
        return cur.fetchall()
