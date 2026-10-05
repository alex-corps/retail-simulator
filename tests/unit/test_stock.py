from __future__ import annotations

import pytest

from retail_sim.core.stock import DayStock, NegativeStockError, compute_opening_stock


def test_compute_opening_stock_adds_deltas_and_drops_zeros() -> None:
    base = {(1, 10): 5, (1, 11): 2}
    deltas = {(1, 10): 3, (1, 11): -2, (2, 10): 4}

    assert compute_opening_stock(base, deltas) == {(1, 10): 8, (2, 10): 4}


def test_compute_opening_stock_raises_on_negative() -> None:
    with pytest.raises(NegativeStockError) as exc_info:
        compute_opening_stock({(1, 10): 1}, {(1, 10): -2})

    error = exc_info.value
    assert error.storage_location_id == 1
    assert error.product_id == 10
    assert error.quantity == -1


def test_day_stock_current_includes_today_and_apply() -> None:
    key = (1, 10)
    stock = DayStock({key: 5}, {key: -2})

    assert stock.opening(key) == 5
    assert stock.current(key) == 3
    assert stock.current((1, 99)) == 0

    stock.apply(key, 4)

    assert stock.current(key) == 7
    assert stock.opening(key) == 5


def test_day_stock_apply_rejects_negative_and_keeps_quantity() -> None:
    key = (1, 10)
    stock = DayStock({key: 2})

    with pytest.raises(NegativeStockError) as exc_info:
        stock.apply(key, -3)

    assert exc_info.value.quantity == -1
    assert stock.current(key) == 2


def test_day_stock_zero_quantity_is_tracked_but_not_positive() -> None:
    depleted = (1, 10)
    remaining = (1, 11)
    other_location = (2, 11)
    stock = DayStock({depleted: 2, remaining: 1, other_location: 4})
    stock.apply(depleted, -2)

    assert stock.current(depleted) == 0
    assert stock.positive_keys() == [remaining, other_location]
    assert stock.items_for_location(1) == {10: 0, 11: 1}
    assert stock.items_for_location(2) == {11: 4}
    assert stock.items_for_location(3) == {}


def test_day_stock_rejects_negative_opening_and_today_delta() -> None:
    with pytest.raises(NegativeStockError):
        DayStock({(1, 10): -1})
    with pytest.raises(NegativeStockError):
        DayStock({(1, 10): 1}, {(1, 10): -5})
