from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from retail_sim.simulation.invariants import check_day_invariants
from retail_sim.steps.s0_opening_stock import run_opening_stock
from retail_sim.steps.s1_supplier import run_supplier
from retail_sim.steps.s2_assortment import run_assortment
from retail_sim.steps.s3_replenish import rollback_replenish, run_replenish
from retail_sim.steps.s4_sales import rollback_sales, run_sales

if TYPE_CHECKING:
    from datetime import date

    from psycopg import Connection

    from retail_sim.steps.s1_supplier import SupplierResult
    from retail_sim.steps.s2_assortment import AssortmentResult
    from retail_sim.steps.s3_replenish import ReplenishResult
    from retail_sim.steps.s4_sales import SalesResult


@dataclass(frozen=True, slots=True)
class DayResult:
    day: date
    supplier: SupplierResult
    assortment: AssortmentResult
    replenish: ReplenishResult
    sales: SalesResult


def run_day(conn: Connection[Any], day: date, seed: int) -> DayResult:
    """Один день — одна транзакция. Продажи снимаются раньше отгрузки."""
    with conn.transaction():
        stock = run_opening_stock(conn, day)
        rollback_sales(conn, day, stock)
        rollback_replenish(conn, day, stock)
        supplier = run_supplier(conn, day, stock)
        assortment = run_assortment(conn, day, stock, seed)
        replenish = run_replenish(conn, day, stock)
        sales = run_sales(conn, day, stock, seed)
        check_day_invariants(conn, day)
        return DayResult(day, supplier, assortment, replenish, sales)
