from __future__ import annotations

import pytest

from retail_sim.core.allocation import allocate


def test_allocate_gives_full_demand_when_stock_is_enough() -> None:
    assert allocate(10, {2: 4, 1: 3}) == {1: 3, 2: 4}


def test_allocate_splits_equal_demand_in_half() -> None:
    assert allocate(10, {1: 7, 2: 7}) == {1: 5, 2: 5}


def test_allocate_gives_remainder_to_smaller_store_id() -> None:
    assert allocate(7, {3: 3, 1: 3, 2: 3}) == {1: 3, 2: 2, 3: 2}


def test_allocate_gives_remainder_to_larger_fraction() -> None:
    # 5 * 10/11 = 4 и 6/11, 5 * 1/11 = 5/11. Лишняя штука уходит первому магазину.
    assert allocate(5, {1: 10, 2: 1}) == {1: 5}


def test_allocate_zero_stock_ships_nothing() -> None:
    assert allocate(0, {1: 5}) == {}


def test_allocate_empty_demand_ships_nothing() -> None:
    assert allocate(5, {}) == {}
    assert allocate(5, {1: 0}) == {}


def test_allocate_never_exceeds_demand_or_stock() -> None:
    cases = [
        (10, {1: 7, 2: 7}),
        (7, {1: 3, 2: 3, 3: 3}),
        (0, {1: 5}),
        (5, {}),
        (1, {2: 4, 1: 4, 3: 4}),
        (100, {1: 3, 2: 4}),
        (5, {1: 10, 2: 1}),
    ]
    for available, demands in cases:
        granted = allocate(available, demands)
        assert sum(granted.values()) == min(available, sum(demands.values()))
        assert all(granted[store_id] <= demands[store_id] for store_id in granted)


def test_allocate_rejects_negative_inputs() -> None:
    with pytest.raises(ValueError, match="available"):
        allocate(-1, {1: 1})
    with pytest.raises(ValueError, match="demand"):
        allocate(1, {1: -1})
