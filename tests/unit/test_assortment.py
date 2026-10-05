from __future__ import annotations

import random
from decimal import ROUND_HALF_UP, Decimal

import pytest

from retail_sim.core.assortment import (
    allocate_quotas,
    build_optimized_items,
    find_delisted,
    pick_best,
    pick_random,
    store_avg_sales,
)
from retail_sim.core.stock import DayStock
from retail_sim.domain.models import Product
from retail_sim.rng import make_rng


def _product(product_id: int, category_l2: str, avg: str) -> Product:
    return Product(
        id=product_id,
        category_l1="Food",
        category_l2=category_l2,
        name=f"sku-{product_id}",
        purchase_price=Decimal("1.00"),
        retail_price=Decimal("2.00"),
        avg_daily_sales=Decimal(avg),
    )


def test_make_rng_repeats_for_the_same_keys() -> None:
    first = make_rng(7, "2026-06-01", 3).random()
    second = make_rng(7, "2026-06-01", 3).random()
    other_store = make_rng(7, "2026-06-01", 4).random()

    assert first == second
    assert first != other_store


def test_allocate_quotas_splits_remainder_and_repeats() -> None:
    sizes = {("Food", "A"): 10, ("Food", "B"): 10, ("Food", "C"): 10, ("Food", "D"): 10}

    first = allocate_quotas(10, sizes, make_rng(1, "quotas"))
    second = allocate_quotas(10, sizes, make_rng(1, "quotas"))

    assert first == second
    assert sum(first.values()) == 10
    assert max(first.values()) - min(first.values()) <= 1
    assert all(quota <= sizes[key] for key, quota in first.items())


def test_allocate_quotas_moves_unfilled_base_to_subcategories_with_stock() -> None:
    sizes = {("Food", "A"): 1, ("Food", "B"): 100}

    assert allocate_quotas(10, sizes, random.Random(0)) == {("Food", "A"): 1, ("Food", "B"): 9}


def test_allocate_quotas_samples_subcategories_when_capacity_is_smaller() -> None:
    sizes = {("Food", "A"): 5, ("Food", "B"): 5, ("Food", "C"): 5, ("Food", "D"): 5}

    first = allocate_quotas(2, sizes, make_rng(3, "small"))
    second = allocate_quotas(2, sizes, make_rng(3, "small"))

    assert first == second
    assert sum(first.values()) == 2
    assert set(first.values()) == {1}


def test_allocate_quotas_takes_the_whole_catalog_and_ignores_empty_groups() -> None:
    sizes = {("Food", "A"): 2, ("Food", "B"): 0, ("Food", "C"): 3}

    assert allocate_quotas(100, sizes, random.Random(0)) == {("Food", "A"): 2, ("Food", "C"): 3}
    assert allocate_quotas(0, sizes, random.Random(0)) == {}


def test_allocate_quotas_gives_extra_slots_to_the_stronger_next_sku() -> None:
    sizes = {("Food", "A"): 1, ("Food", "B"): 5, ("Food", "C"): 5, ("Food", "D"): 5}
    priority = {
        ("Food", "A"): (Decimal("9"),),
        ("Food", "B"): (Decimal("8"), Decimal("7"), Decimal("100")),
        ("Food", "C"): (Decimal("8"), Decimal("7"), Decimal("1")),
        ("Food", "D"): (Decimal("8"), Decimal("7"), Decimal("50")),
    }

    quotas = allocate_quotas(9, sizes, random.Random(0), priority)

    assert quotas == {("Food", "A"): 1, ("Food", "B"): 3, ("Food", "C"): 2, ("Food", "D"): 3}


def test_allocate_quotas_rejects_negative_capacity() -> None:
    with pytest.raises(ValueError, match="capacity"):
        allocate_quotas(-1, {}, random.Random(0))


def test_pick_random_repeats_for_the_same_seed() -> None:
    groups = {("Food", "A"): [1, 2, 3, 4], ("Food", "B"): [5, 6, 7]}
    quotas = {("Food", "A"): 2, ("Food", "B"): 1}

    first = pick_random(groups, quotas, make_rng(4, "pick"))
    second = pick_random(groups, quotas, make_rng(4, "pick"))

    assert first == second
    assert len(first) == 3
    assert len([product_id for product_id in first if product_id <= 4]) == 2


def test_pick_best_breaks_sales_ties_by_product_id() -> None:
    groups = {
        ("Food", "A"): [
            _product(2, "A", "10"),
            _product(1, "A", "10"),
            _product(3, "A", "9"),
        ]
    }

    assert pick_best(groups, {("Food", "A"): 2}) == [1, 2]


def test_store_avg_sales_is_within_thirty_percent_and_repeats() -> None:
    base = Decimal("10.00")
    low = (base * Decimal("0.7")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    high = (base * Decimal("1.3")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    rng = random.Random(1)
    values = [store_avg_sales(base, rng) for _ in range(100)]

    assert values[0] == store_avg_sales(base, random.Random(1))
    assert all(value == value.quantize(Decimal("0.01")) for value in values)
    assert all(low <= value <= high for value in values)


def test_build_optimized_items_keeps_the_average_of_skus_that_stay() -> None:
    items = build_optimized_items(
        {1: Decimal("4.00")},
        [2, 1],
        {1: _product(1, "A", "30.00"), 2: _product(2, "A", "10.00")},
        random.Random(2),
    )

    assert items[0] == (1, Decimal("4.00"))
    assert items[1][0] == 2
    assert Decimal("7.00") <= items[1][1] <= Decimal("13.00")


def test_find_delisted_skips_zero_stock_and_skus_that_stay() -> None:
    stock = DayStock({(5, 1): 4, (5, 2): 9})

    assert find_delisted([1, 2, 3], [2], 5, stock) == {1: 4}
