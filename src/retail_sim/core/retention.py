from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

DAILY_WINDOW_DAYS = 21
WEEKLY_WINDOW_DAYS = 70


def should_retain(stock_date: date, today: date) -> bool:
    age_days = (today - stock_date).days
    if age_days <= DAILY_WINDOW_DAYS:
        return True
    if age_days <= WEEKLY_WINDOW_DAYS:
        return stock_date.weekday() == 0 or stock_date.day == 1
    return stock_date.day == 1


def dates_to_prune(existing: Iterable[date], today: date) -> list[date]:
    return sorted(stock_date for stock_date in existing if not should_retain(stock_date, today))
