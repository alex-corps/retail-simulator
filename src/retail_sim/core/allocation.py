from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


def allocate(available: int, demands: Mapping[int, int]) -> dict[int, int]:
    # Дефицит склада делим пропорционально потребности.
    # Остаток штук получают наибольшие дробные части, при равенстве — меньший store_id.
    if available < 0:
        raise ValueError("available must be >= 0")
    if any(quantity < 0 for quantity in demands.values()):
        raise ValueError("demand must be >= 0")
    requested = {store_id: quantity for store_id, quantity in demands.items() if quantity > 0}
    if available == 0 or not requested:
        return {}
    total = sum(requested.values())
    if available >= total:
        return dict(sorted(requested.items()))

    shares: dict[int, int] = {}
    remainders: list[tuple[Fraction, int]] = []
    assigned = 0
    for store_id in sorted(requested):
        exact = Fraction(available * requested[store_id], total)
        share = int(exact)
        shares[store_id] = share
        assigned += share
        remainders.append((exact - share, store_id))
    remainders.sort(key=lambda item: (-item[0], item[1]))
    for _, store_id in remainders[: available - assigned]:
        shares[store_id] += 1
    return {store_id: share for store_id, share in shares.items() if share > 0}
