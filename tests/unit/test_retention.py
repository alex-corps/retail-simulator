from __future__ import annotations

from datetime import date, timedelta

from retail_sim.core.retention import dates_to_prune, should_retain

TODAY = date(2026, 10, 5)


def test_daily_window_keeps_every_day() -> None:
    assert should_retain(TODAY, TODAY)
    assert should_retain(TODAY - timedelta(days=21), TODAY)
    assert should_retain(TODAY - timedelta(days=3), TODAY)
    assert should_retain(TODAY + timedelta(days=1), TODAY)


def test_age_22_drops_day_that_is_not_monday_or_month_start() -> None:
    stock_date = TODAY - timedelta(days=22)

    assert stock_date.weekday() != 0
    assert stock_date.day != 1
    assert not should_retain(stock_date, TODAY)


def test_weekly_window_keeps_monday_and_month_start() -> None:
    monday = TODAY - timedelta(days=28)
    month_start = date(2026, 9, 1)
    ordinary = date(2026, 9, 2)

    assert monday.weekday() == 0
    assert 22 <= (TODAY - month_start).days <= 70
    assert 22 <= (TODAY - ordinary).days <= 70
    assert should_retain(monday, TODAY)
    assert should_retain(month_start, TODAY)
    assert not should_retain(ordinary, TODAY)


def test_age_70_keeps_monday_and_age_71_keeps_only_month_start() -> None:
    day_70 = TODAY - timedelta(days=70)
    day_71 = TODAY - timedelta(days=71)
    month_start = date(2026, 7, 1)

    assert day_70.weekday() == 0
    assert day_70.day != 1
    assert day_71.day != 1
    assert (TODAY - month_start).days >= 71
    assert should_retain(day_70, TODAY)
    assert not should_retain(day_71, TODAY)
    assert should_retain(month_start, TODAY)
    assert not should_retain(date(2026, 7, 15), TODAY)


def test_dates_to_prune_returns_sorted_dropped_dates() -> None:
    kept = TODAY - timedelta(days=1)
    dropped_weekly = TODAY - timedelta(days=22)
    dropped_old = date(2026, 6, 15)

    assert dates_to_prune([kept, dropped_weekly, dropped_old, TODAY], TODAY) == [
        dropped_old,
        dropped_weekly,
    ]
