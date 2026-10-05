from __future__ import annotations

from datetime import date
from decimal import Decimal
from fractions import Fraction

from retail_sim.core.demand import average_usage, order_quantity, replenish_quantity, round_half_up


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


def test_round_half_up_rounds_half_away_from_zero() -> None:
    assert round_half_up(Fraction(5, 2)) == 3
    assert round_half_up(Fraction(249, 100)) == 2
    assert round_half_up(Fraction(1, 2)) == 1


def test_replenish_quantity_uses_assortment_average_for_first_receipt() -> None:
    # 3.50 вверх до 4, цель 7 дней, остаток 0 → 28.
    assert replenish_quantity(Fraction(0), 0, 7, Decimal("3.50")) == 28


def test_replenish_quantity_ignores_assortment_when_stock_remains() -> None:
    assert replenish_quantity(Fraction(0), 5, 7, Decimal("3.50")) == 0


def test_replenish_quantity_zero_assortment_orders_nothing() -> None:
    assert replenish_quantity(Fraction(0), 0, 7, Decimal("0")) == 0


def test_replenish_quantity_zero_stock_keeps_need() -> None:
    # ceil(2.2) = 3, половина вверх даёт 2, при нулевом остатке остаётся потребность.
    assert replenish_quantity(Fraction(11, 5), 0, 1, Decimal("0")) == 3


def test_replenish_quantity_with_stock_does_not_lift_to_average() -> None:
    # ceil(2.5 * 1 - 2) = 1. Округлённый расход 3 не подменяет потребность: остаток уже не ноль.
    assert replenish_quantity(Fraction(5, 2), 2, 1, Decimal("0")) == 1


def test_replenish_quantity_uses_sales_average() -> None:
    # 10 шт за 3 дня, цель 7, остаток 0: ceil(70/3) = 24. Средняя ассортимента не участвует.
    assert replenish_quantity(Fraction(10, 3), 0, 7, Decimal("99")) == 24
