from __future__ import annotations

from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from typing import Any, cast

import pytest

from retail_sim.simulation.day_runner import run_day
from retail_sim.steps.s1_supplier import SupplierResult
from retail_sim.steps.s2_assortment import AssortmentResult
from retail_sim.steps.s3_replenish import ReplenishResult
from retail_sim.steps.s4_sales import SalesResult


def test_run_day_step_order(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class _Conn:
        def transaction(self) -> nullcontext[None]:
            calls.append("tx")
            return nullcontext()

    def opening(_conn: object, _day: date) -> str:
        calls.append("s0")
        return "stock"

    def rollback_sales(_conn: object, _day: date, stock: object) -> int:
        calls.append("rollback_sales")
        assert stock == "stock"
        return 0

    def rollback_replenish(_conn: object, _day: date, stock: object) -> int:
        calls.append("rollback_replenish")
        assert stock == "stock"
        return 0

    def supplier(_conn: object, _day: date, _stock: object) -> SupplierResult:
        calls.append("s1")
        return SupplierResult(False, 1, 2, 3)

    def assortment(_conn: object, _day: date, _stock: object, seed: int) -> AssortmentResult:
        calls.append("s2")
        assert seed == 7
        return AssortmentResult(0, 0, 0)

    def replenish(_conn: object, _day: date, _stock: object) -> ReplenishResult:
        calls.append("s3")
        return ReplenishResult(1, 2, 3, 4)

    def sales(_conn: object, _day: date, _stock: object, seed: int) -> SalesResult:
        calls.append("s4")
        assert seed == 7
        return SalesResult(1, 2, 3, 4, Decimal("10.00"))

    def invariants(_conn: object, _day: date) -> None:
        calls.append("invariants")

    monkeypatch.setattr("retail_sim.simulation.day_runner.run_opening_stock", opening)
    monkeypatch.setattr("retail_sim.simulation.day_runner.rollback_sales", rollback_sales)
    monkeypatch.setattr("retail_sim.simulation.day_runner.rollback_replenish", rollback_replenish)
    monkeypatch.setattr("retail_sim.simulation.day_runner.run_supplier", supplier)
    monkeypatch.setattr("retail_sim.simulation.day_runner.run_assortment", assortment)
    monkeypatch.setattr("retail_sim.simulation.day_runner.run_replenish", replenish)
    monkeypatch.setattr("retail_sim.simulation.day_runner.run_sales", sales)
    monkeypatch.setattr("retail_sim.simulation.day_runner.check_day_invariants", invariants)

    result = run_day(cast("Any", _Conn()), date(2026, 6, 1), 7)

    assert calls == [
        "tx",
        "s0",
        "rollback_sales",
        "rollback_replenish",
        "s1",
        "s2",
        "s3",
        "s4",
        "invariants",
    ]
    assert result.day == date(2026, 6, 1)
    assert result.sales.units_sold == 4
