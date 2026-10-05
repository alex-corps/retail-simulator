from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from retail_sim.domain.enums import OperationType

if TYPE_CHECKING:
    from datetime import date

    from psycopg import Connection

RULE_NON_NEGATIVE_STOCK = "non_negative_stock"
RULE_TRANSFER_BALANCE = "transfer_balance"
RULE_OPERATION_LOCATION = "operation_location"
RULE_SALES_MATCH_RECEIPTS = "sales_match_receipts"
RULE_RECEIPT_HAS_LINES = "receipt_has_lines"
RULE_RECEIPT_HOURS = "receipt_hours"
RULE_SALE_IN_ASSORTMENT = "sale_in_assortment"

_SAMPLE_LIMIT = 5


class InvariantError(Exception):
    def __init__(self, rule: str, details: tuple[str, ...]) -> None:
        self.rule = rule
        self.details = details
        sample = "; ".join(details)
        super().__init__(f"Invariant {rule} failed: {sample}")


def check_day_invariants(conn: Connection[Any], day: date) -> None:
    # Проверки идут в транзакции дня: любая ошибка откатывает этот день целиком.
    next_day = day + timedelta(days=1)
    params: dict[str, Any] = {
        "day": day,
        "next_day": next_day,
        "transfer": str(OperationType.TRANSFER),
        "receipt": str(OperationType.RECEIPT),
        "sale": str(OperationType.SALE),
        "limit": _SAMPLE_LIMIT,
    }
    _check(conn, RULE_NON_NEGATIVE_STOCK, _NON_NEGATIVE_SQL, params)
    _check(conn, RULE_TRANSFER_BALANCE, _TRANSFER_SQL, params)
    _check(conn, RULE_OPERATION_LOCATION, _LOCATION_SQL, params)
    _check(conn, RULE_SALES_MATCH_RECEIPTS, _SALES_MATCH_SQL, params)
    _check(conn, RULE_RECEIPT_HAS_LINES, _EMPTY_RECEIPT_SQL, params)
    _check(conn, RULE_RECEIPT_HOURS, _HOURS_SQL, params)
    _check(conn, RULE_SALE_IN_ASSORTMENT, _ASSORTMENT_SQL, params)


def _check(conn: Connection[Any], rule: str, sql: str, params: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    if not rows:
        return
    details = tuple(", ".join(str(column) for column in row) for row in rows)
    raise InvariantError(rule, details)


_NON_NEGATIVE_SQL = """
SELECT storage_location_id, product_id, quantity
FROM (
    SELECT storage_location_id, product_id, SUM(quantity) AS quantity
    FROM (
        SELECT storage_location_id, product_id, quantity
        FROM daily_opening_stock
        WHERE stock_date = %(day)s
        UNION ALL
        SELECT storage_location_id, product_id, quantity
        FROM inventory_movements
        WHERE op_date = %(day)s
    ) AS parts
    GROUP BY storage_location_id, product_id
) AS totals
WHERE quantity < 0
LIMIT %(limit)s
"""

_TRANSFER_SQL = """
SELECT product_id, SUM(quantity) AS quantity
FROM inventory_movements
WHERE op_date = %(day)s
  AND op_type = %(transfer)s
GROUP BY product_id
HAVING SUM(quantity) <> 0
LIMIT %(limit)s
"""

_LOCATION_SQL = """
SELECT id, op_type, storage_location_id
FROM inventory_movements
WHERE op_date = %(day)s
  AND (
        (
            op_type = %(receipt)s
            AND NOT EXISTS (
                SELECT 1
                FROM warehouses
                WHERE warehouses.storage_location_id = inventory_movements.storage_location_id
            )
        )
        OR (
            op_type = %(sale)s
            AND (
                receiver_location_id IS NOT NULL
                OR NOT EXISTS (
                    SELECT 1
                    FROM stores
                    WHERE stores.storage_location_id = inventory_movements.storage_location_id
                )
            )
        )
      )
LIMIT %(limit)s
"""

_SALES_MATCH_SQL = """
WITH sale_qty AS (
    SELECT stores.id AS store_id, SUM(-movements.quantity) AS units
    FROM inventory_movements AS movements
    JOIN stores ON stores.storage_location_id = movements.storage_location_id
    WHERE movements.op_date = %(day)s
      AND movements.op_type = %(sale)s
    GROUP BY stores.id
),
receipt_qty AS (
    SELECT receipts.store_id, SUM(lines.quantity) AS units
    FROM receipt_lines AS lines
    JOIN receipts ON receipts.id = lines.receipt_id
    WHERE receipts.receipt_ts >= %(day)s
      AND receipts.receipt_ts < %(next_day)s
    GROUP BY receipts.store_id
)
SELECT
    COALESCE(sale_qty.store_id, receipt_qty.store_id) AS store_id,
    COALESCE(sale_qty.units, 0) AS sold,
    COALESCE(receipt_qty.units, 0) AS billed
FROM sale_qty
FULL OUTER JOIN receipt_qty ON receipt_qty.store_id = sale_qty.store_id
WHERE COALESCE(sale_qty.units, 0) <> COALESCE(receipt_qty.units, 0)
LIMIT %(limit)s
"""

_EMPTY_RECEIPT_SQL = """
SELECT receipts.id
FROM receipts
WHERE receipts.receipt_ts >= %(day)s
  AND receipts.receipt_ts < %(next_day)s
  AND NOT EXISTS (
      SELECT 1
      FROM receipt_lines
      WHERE receipt_lines.receipt_id = receipts.id
  )
LIMIT %(limit)s
"""

_HOURS_SQL = """
SELECT receipts.id, receipts.receipt_ts
FROM receipts
JOIN stores ON stores.id = receipts.store_id
WHERE receipts.receipt_ts >= %(day)s
  AND receipts.receipt_ts < %(next_day)s
  AND (
        receipts.receipt_ts::time < stores.open_from
        OR receipts.receipt_ts::time > stores.open_to
      )
LIMIT %(limit)s
"""

_ASSORTMENT_SQL = """
SELECT receipts.id, lines.product_id
FROM receipt_lines AS lines
JOIN receipts ON receipts.id = lines.receipt_id
WHERE receipts.receipt_ts >= %(day)s
  AND receipts.receipt_ts < %(next_day)s
  AND NOT EXISTS (
      SELECT 1
      FROM store_assortment
      WHERE store_assortment.store_id = receipts.store_id
        AND store_assortment.product_id = lines.product_id
  )
LIMIT %(limit)s
"""
