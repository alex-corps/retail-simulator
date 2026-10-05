from __future__ import annotations

from datetime import date

import pytest

from retail_sim.domain.calendar import is_supplier_day


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        (date(2026, 6, 1), True),
        (date(2026, 6, 4), True),
        (date(2026, 6, 2), False),
        (date(2026, 6, 3), False),
        (date(2026, 6, 5), False),
        (date(2026, 6, 6), False),
        (date(2026, 6, 7), False),
    ],
)
def test_is_supplier_day(day: date, expected: bool) -> None:
    assert is_supplier_day(day) is expected
