from __future__ import annotations

from typing import TYPE_CHECKING, Any

from psycopg.rows import class_row

from retail_sim.domain.models import CalculationParameters

if TYPE_CHECKING:
    from psycopg import Connection

_PARAMETER_COLUMNS = """
    id,
    avg_receipts_per_day,
    avg_receipt_amount,
    avg_sku_capacity,
    min_receipt_amount,
    max_receipt_amount,
    target_stock_days_warehouse,
    target_stock_days_store
"""


class CalculationParametersMissingError(Exception):
    """Raised when the single calculation_parameters row is absent."""


def get_calculation_parameters(conn: Connection[Any]) -> CalculationParameters:
    with conn.cursor(row_factory=class_row(CalculationParameters)) as cur:
        cur.execute(
            f"""
            SELECT {_PARAMETER_COLUMNS}
            FROM calculation_parameters
            WHERE id = 1
            """
        )
        row = cur.fetchone()
    if row is None:
        raise CalculationParametersMissingError("calculation_parameters row id=1 is missing")
    return row
