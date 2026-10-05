from __future__ import annotations

from datetime import date
from fractions import Fraction

from retail_sim.core.demand import average_usage, order_quantity


def test_average_usage_counts_outflow_day_without_stock() -> None:
    outflow_day = date(2026, 5, 30)

    assert average_usage({outflow_day: 10}, set()) == Fraction(10, 1)


def test_average_usage_counts_stock_day_without_outflow() -> None:
    outflow_day = date(2026, 5, 30)
    stock_day = date(2026, 5, 31)

    assert average_usage({outflow_day: 10}, {stock_day}) == Fraction(10, 2)


def test_average_usage_counts_shared_day_once() -> None:
    day = date(2026, 5, 30)

    assert average_usage({day: 10}, {day}) == Fraction(10, 1)


def test_average_usage_empty_is_zero() -> None:
    assert average_usage({}, set()) == Fraction(0)


def test_order_quantity_exact_cover_is_zero() -> None:
    # 10 шт за 3 активных дня, цель 3 дня, остаток 10: потребность ровно 0.
    avg = average_usage(
        {date(2026, 5, 1): 10},
        {date(2026, 5, 2), date(2026, 5, 3)},
    )

    assert avg == Fraction(10, 3)
    assert order_quantity(avg, 10, 3) == 0


def test_order_quantity_ceils_fractional_need() -> None:
    assert order_quantity(Fraction(10, 3), 0, 2) == 7


def test_order_quantity_is_zero_when_stock_covers_target() -> None:
    assert order_quantity(Fraction(1), 100, 3) == 0
