from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from math import ceil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Set
    from datetime import date

# Окно расхода: 21 день до расчётного, сам день в него не входит.
USAGE_WINDOW_DAYS = 21


def average_usage(
    outflow_by_day: Mapping[date, int],
    stock_days: Set[date],
) -> Fraction:
    # День входит в делитель, если была отгрузка или остаток на начало дня.
    outflow_days = {day for day, quantity in outflow_by_day.items() if quantity > 0}
    active_days = outflow_days | set(stock_days)
    if not active_days:
        return Fraction(0)
    total = sum(outflow_by_day[day] for day in outflow_days)
    return Fraction(total, len(active_days))


def order_quantity(avg: Fraction, current: int, target_days: int) -> int:
    # Сколько заказать, чтобы покрыть целевой запас; вверх и не ниже нуля.
    need = avg * target_days - current
    if need <= 0:
        return 0
    return ceil(need)


def round_half_up(value: Fraction) -> int:
    # Половина уходит вверх: 2.5 → 3. Встроенный round() отдал бы 2.
    amount = Decimal(value.numerator) / Decimal(value.denominator)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def replenish_quantity(
    avg: Fraction,
    current: int,
    target_days: int,
    assortment_avg: Decimal,
) -> int:
    # Первичный приход: расхода не было и полка пустая — берём среднюю из ассортимента.
    if avg == 0 and current == 0:
        avg = Fraction(ceil(assortment_avg))
    need = order_quantity(avg, current, target_days)
    # При нулевом остатке берём максимум потребности и округлённого расхода.
    if current == 0:
        return max(need, round_half_up(avg))
    return need
