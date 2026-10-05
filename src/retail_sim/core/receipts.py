from __future__ import annotations

from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import random
    from collections.abc import Mapping
    from datetime import date, time

# 70% чеков считаются от среднего, остальные — из полного диапазона.
_TYPICAL_SHARE = 0.7
_REVENUE_LOW = 0.8
_REVENUE_HIGH = 1.2
_TYPICAL_LOW = 0.5
_TYPICAL_HIGH = 2.0


def plan_day_revenue(
    avg_receipt_amount_kop: int,
    store_avg_receipts: Decimal,
    rng: random.Random,
) -> int:
    factor = Decimal(str(rng.uniform(_REVENUE_LOW, _REVENUE_HIGH)))
    revenue = Decimal(avg_receipt_amount_kop) * store_avg_receipts * factor
    return int(revenue.to_integral_value(rounding=ROUND_HALF_UP))


def receipt_amount(
    avg_kop: int,
    min_kop: int,
    max_kop: int,
    rng: random.Random,
) -> int:
    # 70% — средний чек от половины до двух; 30% — равномерно между минимумом и максимумом.
    if rng.random() < _TYPICAL_SHARE:
        factor = Decimal(str(rng.uniform(_TYPICAL_LOW, _TYPICAL_HIGH)))
        amount = Decimal(avg_kop) * factor
    else:
        amount = Decimal(str(rng.uniform(min_kop, max_kop)))
    kopecks = int(amount.to_integral_value(rounding=ROUND_HALF_UP))
    if kopecks <= 0:
        raise ValueError("receipt amount must be positive")
    return kopecks


def plan_receipt_amounts(
    day_revenue_kop: int,
    avg_kop: int,
    min_kop: int,
    max_kop: int,
    rng: random.Random,
) -> list[int]:
    if day_revenue_kop <= 0:
        return []
    amounts: list[int] = []
    total = 0
    # Последний чек остаётся: сумма чеков должна превысить план дня.
    while total <= day_revenue_kop:
        amount = receipt_amount(avg_kop, min_kop, max_kop, rng)
        amounts.append(amount)
        total += amount
    return amounts


def receipt_timestamps(
    day: date,
    open_from: time,
    open_to: time,
    count: int,
    rng: random.Random,
) -> list[datetime]:
    if count <= 0:
        return []
    start = datetime.combine(day, open_from)
    end = datetime.combine(day, open_to)
    span = (end - start).total_seconds()
    if span <= 0:
        raise ValueError("open_from must be earlier than open_to")
    # Сдвиг остаётся внутри слота, поэтому время не выходит за часы работы.
    slot = span / count
    stamps = [
        start + timedelta(seconds=min(slot * index + rng.uniform(0.0, slot), span))
        for index in range(count)
    ]
    stamps.sort()
    return stamps


class AvailableSkus:
    def __init__(self, stock: Mapping[int, int]) -> None:
        # Порядок id фиксирует выбор при одинаковом seed.
        self._ids = [product_id for product_id in sorted(stock) if stock[product_id] > 0]
        self._qty = {product_id: stock[product_id] for product_id in self._ids}

    def __len__(self) -> int:
        return len(self._ids)

    def take(self, rng: random.Random) -> int | None:
        if not self._ids:
            return None
        index = rng.randrange(len(self._ids))
        product_id = self._ids[index]
        remaining = self._qty[product_id] - 1
        if remaining == 0:
            self._qty.pop(product_id)
            last = len(self._ids) - 1
            self._ids[index] = self._ids[last]
            self._ids.pop()
        else:
            self._qty[product_id] = remaining
        return product_id


def fill_receipt(
    amount_kop: int,
    prices_kop: Mapping[int, int],
    pool: AvailableSkus,
    rng: random.Random,
) -> dict[int, int]:
    lines: dict[int, int] = {}
    total = 0
    # Единица, на которой сумма превысила чек, входит в чек.
    while total <= amount_kop:
        product_id = pool.take(rng)
        if product_id is None:
            break
        lines[product_id] = lines.get(product_id, 0) + 1
        total += prices_kop[product_id]
    return lines
