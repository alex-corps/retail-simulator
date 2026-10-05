from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.rows import class_row

from retail_sim.domain.models import Product

if TYPE_CHECKING:
    from psycopg import Connection

_PRODUCT_COLUMNS = """
    id,
    category_l1,
    category_l2,
    name,
    purchase_price,
    retail_price,
    avg_daily_sales
"""


def list_products(conn: Connection[Any]) -> list[Product]:
    with conn.cursor(row_factory=class_row(Product)) as cur:
        cur.execute(
            f"""
            SELECT {_PRODUCT_COLUMNS}
            FROM products
            ORDER BY id
            """
        )
        return cur.fetchall()


def get_product(conn: Connection[Any], product_id: int) -> Product | None:
    with conn.cursor(row_factory=class_row(Product)) as cur:
        cur.execute(
            f"""
            SELECT {_PRODUCT_COLUMNS}
            FROM products
            WHERE id = %s
            """,
            (product_id,),
        )
        return cur.fetchone()
