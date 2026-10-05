from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Any

from retail_sim.core.promo import normalize_price_factor
from retail_sim.db.copy import copy_rows
from retail_sim.domain.models import SalePeriod
from retail_sim.repositories.stores import StoreNotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from psycopg import Connection


def insert_sale_period(
    conn: Connection[Any],
    date_from: date,
    date_to: date,
    price_factor: Decimal,
    store_ids: Sequence[int],
) -> SalePeriod:
    if date_from > date_to:
        raise ValueError("date_from must be on or before date_to")
    unique_ids = list(dict.fromkeys(store_ids))
    if not unique_ids:
        raise ValueError("sale period must include at least one store")
    factor = normalize_price_factor(price_factor)
    _require_stores(conn, unique_ids)
    with conn.transaction():
        period_id = _insert_period(conn, date_from, date_to, factor)
        copy_rows(
            conn,
            "sale_period_stores",
            ("sale_period_id", "store_id"),
            [(period_id, store_id) for store_id in unique_ids],
        )
    return SalePeriod(
        id=period_id,
        date_from=date_from,
        date_to=date_to,
        price_factor=factor,
        store_ids=tuple(unique_ids),
    )


def list_sale_periods(conn: Connection[Any]) -> list[SalePeriod]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                periods.id,
                periods.date_from,
                periods.date_to,
                periods.price_factor,
                COALESCE(
                    array_agg(link.store_id ORDER BY link.store_id)
                        FILTER (WHERE link.store_id IS NOT NULL),
                    '{}'
                ) AS store_ids
            FROM sale_periods AS periods
            LEFT JOIN sale_period_stores AS link ON link.sale_period_id = periods.id
            GROUP BY periods.id
            ORDER BY periods.date_from, periods.id
            """
        )
        rows = cur.fetchall()
    return [
        SalePeriod(
            id=int(period_id),
            date_from=date_from,
            date_to=date_to,
            price_factor=Decimal(price_factor),
            store_ids=tuple(int(store_id) for store_id in store_ids),
        )
        for period_id, date_from, date_to, price_factor, store_ids in rows
    ]


def effective_price_factors(conn: Connection[Any], day: date) -> dict[int, Decimal]:
    # Пересечения не сливаются заранее: на день берётся наибольшая скидка.
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT link.store_id, MIN(periods.price_factor) AS price_factor
            FROM sale_periods AS periods
            JOIN sale_period_stores AS link ON link.sale_period_id = periods.id
            WHERE periods.date_from <= %(day)s
              AND periods.date_to >= %(day)s
            GROUP BY link.store_id
            """,
            {"day": day},
        )
        rows = cur.fetchall()
    return {int(store_id): Decimal(factor) for store_id, factor in rows}


def _require_stores(conn: Connection[Any], store_ids: Sequence[int]) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM stores WHERE id = ANY(%s)", (list(store_ids),))
        found = {int(row[0]) for row in cur.fetchall()}
    for store_id in store_ids:
        if store_id not in found:
            raise StoreNotFoundError(store_id)


def _insert_period(
    conn: Connection[Any],
    date_from: date,
    date_to: date,
    price_factor: Decimal,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sale_periods (date_from, date_to, price_factor)
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (date_from, date_to, price_factor),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("sale_periods insert did not return an id")
    return int(row[0])
