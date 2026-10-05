from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

StockKey = tuple[int, int]


class NegativeStockError(Exception):
    def __init__(self, storage_location_id: int, product_id: int, quantity: int) -> None:
        self.storage_location_id = storage_location_id
        self.product_id = product_id
        self.quantity = quantity
        super().__init__(
            f"Negative stock at location {storage_location_id} "
            f"for product {product_id}: {quantity}"
        )


def compute_opening_stock(
    base: Mapping[StockKey, int],
    deltas: Mapping[StockKey, int],
) -> dict[StockKey, int]:
    opening: dict[StockKey, int] = {}
    for key in set(base) | set(deltas):
        quantity = base.get(key, 0) + deltas.get(key, 0)
        if quantity < 0:
            raise NegativeStockError(key[0], key[1], quantity)
        if quantity > 0:
            opening[key] = quantity
    return opening


class DayStock:
    def __init__(
        self,
        opening: Mapping[StockKey, int],
        today_deltas: Mapping[StockKey, int] | None = None,
    ) -> None:
        self._opening: dict[StockKey, int] = {}
        for key, quantity in opening.items():
            if quantity < 0:
                raise NegativeStockError(key[0], key[1], quantity)
            if quantity > 0:
                self._opening[key] = quantity
        self._deltas: dict[StockKey, int] = {}
        if today_deltas is not None:
            for key, delta in today_deltas.items():
                self.apply(key, delta)

    def opening(self, key: StockKey) -> int:
        return self._opening.get(key, 0)

    def current(self, key: StockKey) -> int:
        return self._opening.get(key, 0) + self._deltas.get(key, 0)

    def apply(self, key: StockKey, delta: int) -> None:
        if delta == 0:
            return
        quantity = self.current(key) + delta
        if quantity < 0:
            raise NegativeStockError(key[0], key[1], quantity)
        updated = self._deltas.get(key, 0) + delta
        if updated == 0:
            self._deltas.pop(key, None)
        else:
            self._deltas[key] = updated

    def items_for_location(self, location_id: int) -> dict[int, int]:
        product_ids = sorted(
            product_id
            for stored_location_id, product_id in self._tracked_keys()
            if stored_location_id == location_id
        )
        return {
            product_id: self.current((location_id, product_id)) for product_id in product_ids
        }

    def positive_keys(self) -> list[StockKey]:
        return sorted(key for key in self._tracked_keys() if self.current(key) > 0)

    def _tracked_keys(self) -> set[StockKey]:
        return set(self._opening) | set(self._deltas)
