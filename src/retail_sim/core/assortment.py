from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import random
    from collections.abc import Collection, Mapping, Sequence

    from retail_sim.core.stock import DayStock
    from retail_sim.domain.models import Product

SubKey = tuple[str, str]

_CENT = Decimal("0.01")
_FACTOR_LOW = 0.7
_FACTOR_HIGH = 1.3


def allocate_quotas(
    capacity: int,
    sizes: Mapping[SubKey, int],
    rng: random.Random,
    priority: Mapping[SubKey, Sequence[Decimal]] | None = None,
) -> dict[SubKey, int]:
    if capacity < 0:
        raise ValueError("capacity must be >= 0")
    available = {key: size for key, size in sizes.items() if size > 0}
    total = sum(available.values())
    if capacity == 0 or total == 0:
        return {}
    if capacity >= total:
        return dict(available)

    keys = sorted(available)
    subcategory_count = len(keys)
    if capacity < subcategory_count:
        return dict.fromkeys(rng.sample(keys, capacity), 1)

    base = capacity // subcategory_count
    quotas = {key: min(base, available[key]) for key in keys}
    leftover = capacity - sum(quotas.values())
    # One extra SKU per subcategory per round, so unconstrained quotas stay within 1.
    while leftover > 0:
        room = [key for key in keys if quotas[key] < available[key]]
        if not room:
            break
        grant = min(leftover, len(room))
        for key in _choose_recipients(room, grant, quotas, rng, priority):
            quotas[key] += 1
        leftover -= grant
    return {key: quota for key, quota in quotas.items() if quota > 0}


def pick_random(
    groups: Mapping[SubKey, Sequence[int]],
    quotas: Mapping[SubKey, int],
    rng: random.Random,
) -> list[int]:
    chosen: list[int] = []
    for key in sorted(quotas):
        quota = quotas[key]
        if quota <= 0:
            continue
        pool = list(groups[key])
        if quota > len(pool):
            raise ValueError(f"quota {quota} exceeds {len(pool)} SKUs in {key}")
        chosen.extend(rng.sample(pool, quota))
    return chosen


def pick_best(
    groups: Mapping[SubKey, Sequence[Product]],
    quotas: Mapping[SubKey, int],
) -> list[int]:
    chosen: list[int] = []
    for key in sorted(quotas):
        quota = quotas[key]
        if quota <= 0:
            continue
        ranked = sorted(groups[key], key=lambda product: (-product.avg_daily_sales, product.id))
        if quota > len(ranked):
            raise ValueError(f"quota {quota} exceeds {len(ranked)} SKUs in {key}")
        chosen.extend(product.id for product in ranked[:quota])
    return chosen


def store_avg_sales(base: Decimal, rng: random.Random) -> Decimal:
    factor = Decimal(str(rng.uniform(_FACTOR_LOW, _FACTOR_HIGH)))
    return (base * factor).quantize(_CENT, rounding=ROUND_HALF_UP)


def build_optimized_items(
    old_items: Mapping[int, Decimal],
    new_ids: Collection[int],
    products: Mapping[int, Product],
    rng: random.Random,
) -> list[tuple[int, Decimal]]:
    fresh = {
        product_id: store_avg_sales(products[product_id].avg_daily_sales, rng)
        for product_id in sorted(set(new_ids) - set(old_items))
    }
    items: list[tuple[int, Decimal]] = []
    for product_id in sorted(new_ids):
        if product_id in old_items:
            items.append((product_id, old_items[product_id]))
        else:
            items.append((product_id, fresh[product_id]))
    return items


def find_delisted(
    old_ids: Collection[int],
    new_ids: Collection[int],
    store_location_id: int,
    stock: DayStock,
) -> dict[int, int]:
    kept = set(new_ids)
    removed: dict[int, int] = {}
    for product_id in sorted(set(old_ids) - kept):
        quantity = stock.current((store_location_id, product_id))
        if quantity > 0:
            removed[product_id] = quantity
    return removed


def _choose_recipients(
    room: list[SubKey],
    grant: int,
    quotas: Mapping[SubKey, int],
    rng: random.Random,
    priority: Mapping[SubKey, Sequence[Decimal]] | None,
) -> list[SubKey]:
    if priority is None:
        return rng.sample(room, grant)
    ranked = sorted(room, key=lambda key: (-priority[key][quotas[key]], key))
    return ranked[:grant]
