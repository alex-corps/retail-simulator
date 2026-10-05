from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import date

# Понедельник и четверг — дни поставки на склад.
_SUPPLIER_WEEKDAYS = frozenset({0, 3})


def is_supplier_day(day: date) -> bool:
    return day.weekday() in _SUPPLIER_WEEKDAYS
