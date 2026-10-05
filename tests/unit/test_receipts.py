from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest

from retail_sim.core.receipts import (
    AvailableSkus,
    fill_receipt,
    plan_day_revenue,
    plan_receipt_amounts,
    receipt_amount,
    receipt_timestamps,
)


class ScriptedRng(random.Random):
    def __init__(
        self,
        randoms: list[float] | None = None,
        uniforms: list[float] | None = None,
        picks: list[int] | None = None,
    ) -> None:
        super().__init__(0)
        self._randoms = list(randoms or [])
        self._uniforms = list(uniforms or [])
        self._picks = list(picks or [])

    def random(self) -> float:
        return self._randoms.pop(0)

    def uniform(self, a: float, b: float) -> float:
        return self._uniforms.pop(0)

    def randrange(self, start: int, stop: int | None = None, step: int = 1) -> int:
        return self._picks.pop(0)


def test_plan_day_revenue_scales_receipt_count() -> None:
    low = plan_day_revenue(10_000, Decimal("10"), ScriptedRng(uniforms=[0.8]))
    high = plan_day_revenue(10_000, Decimal("10"), ScriptedRng(uniforms=[1.2]))

    assert low == 80_000
    assert high == 120_000


def test_plan_day_revenue_rounds_half_up() -> None:
    assert plan_day_revenue(1, Decimal("1.5"), ScriptedRng(uniforms=[1.0])) == 2


def test_receipt_amount_typical_branch_spans_half_to_double() -> None:
    half = receipt_amount(10_000, 1_000, 50_000, ScriptedRng(randoms=[0.0], uniforms=[0.5]))
    double = receipt_amount(10_000, 1_000, 50_000, ScriptedRng(randoms=[0.69], uniforms=[2.0]))

    assert half == 5_000
    assert double == 20_000


def test_receipt_amount_typical_branch_rounds_half_up() -> None:
    amount = receipt_amount(10_001, 1_000, 50_000, ScriptedRng(randoms=[0.0], uniforms=[0.5]))

    assert amount == 5_001


def test_receipt_amount_wide_branch_keeps_endpoints() -> None:
    low = receipt_amount(10_000, 1_000, 50_000, ScriptedRng(randoms=[0.7], uniforms=[1_000]))
    high = receipt_amount(10_000, 1_000, 50_000, ScriptedRng(randoms=[0.9], uniforms=[50_000]))

    assert low == 1_000
    assert high == 50_000


def test_receipt_amount_wide_branch_rounds_half_up() -> None:
    amount = receipt_amount(10_000, 1_000, 50_000, ScriptedRng(randoms=[0.7], uniforms=[1_000.5]))

    assert amount == 1_001


def test_receipt_amount_rejects_non_positive_result() -> None:
    with pytest.raises(ValueError, match="positive"):
        receipt_amount(0, 1, 2, ScriptedRng(randoms=[0.0], uniforms=[0.5]))


def test_plan_receipt_amounts_includes_receipt_that_exceeds_revenue() -> None:
    amounts = plan_receipt_amounts(
        10_000,
        10_000,
        100,
        50_000,
        ScriptedRng(randoms=[0.0, 0.0], uniforms=[0.5, 1.0]),
    )

    assert amounts == [5_000, 10_000]


def test_plan_receipt_amounts_zero_revenue_is_empty() -> None:
    assert plan_receipt_amounts(0, 10_000, 100, 50_000, ScriptedRng()) == []


def test_receipt_timestamps_stay_inside_opening_hours() -> None:
    day = date(2026, 6, 1)
    stamps = receipt_timestamps(day, time(10, 0), time(21, 0), 5, random.Random(0))

    assert len(stamps) == 5
    assert stamps == sorted(stamps)
    start = datetime.combine(day, time(10, 0))
    end = datetime.combine(day, time(21, 0))
    assert all(start <= stamp <= end for stamp in stamps)


def test_receipt_timestamps_are_deterministic() -> None:
    day = date(2026, 6, 1)
    first = receipt_timestamps(day, time(10, 0), time(21, 0), 4, random.Random(1))
    second = receipt_timestamps(day, time(10, 0), time(21, 0), 4, random.Random(1))

    assert first == second


def test_receipt_timestamps_jitter_can_land_on_closing_time() -> None:
    day = date(2026, 6, 1)
    # 10:00-21:00 длится 39600 секунд, два слота по 19800. Сдвиг на весь слот попадает в конец.
    stamps = receipt_timestamps(
        day,
        time(10, 0),
        time(21, 0),
        2,
        ScriptedRng(uniforms=[19_800, 19_800]),
    )

    assert stamps == [
        datetime.combine(day, time(10, 0)) + timedelta(seconds=19_800),
        datetime.combine(day, time(21, 0)),
    ]


def test_receipt_timestamps_zero_count_is_empty() -> None:
    assert receipt_timestamps(date(2026, 6, 1), time(10, 0), time(21, 0), 0, ScriptedRng()) == []


def test_receipt_timestamps_reject_inverted_hours() -> None:
    with pytest.raises(ValueError, match="open_from"):
        receipt_timestamps(date(2026, 6, 1), time(21, 0), time(10, 0), 1, ScriptedRng(uniforms=[0]))


def test_fill_receipt_includes_crossing_unit_and_aggregates() -> None:
    pool = AvailableSkus({1: 5})

    filled = fill_receipt(10_000, {1: 6_000}, pool, ScriptedRng(picks=[0, 0, 0]))

    assert filled == {1: 2}
    assert pool.take(ScriptedRng(picks=[0])) == 1


def test_fill_receipt_keeps_distinct_skus() -> None:
    pool = AvailableSkus({1: 1, 2: 1})

    filled = fill_receipt(5_000, {1: 4_000, 2: 4_000}, pool, ScriptedRng(picks=[0, 0]))

    assert filled == {1: 1, 2: 1}


def test_fill_receipt_stops_when_stock_runs_out() -> None:
    pool = AvailableSkus({1: 1, 2: 1})

    filled = fill_receipt(100_000, {1: 10, 2: 10}, pool, ScriptedRng(picks=[0, 0, 0]))

    assert filled == {1: 1, 2: 1}
    assert pool.take(ScriptedRng(picks=[0])) is None


def test_fill_receipt_empty_pool_returns_no_lines() -> None:
    pool = AvailableSkus({1: 0, 2: -1})

    assert fill_receipt(100, {1: 10, 2: 10}, pool, ScriptedRng()) == {}
