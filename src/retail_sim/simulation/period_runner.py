from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from psycopg.pq import TransactionStatus

from retail_sim.domain.enums import RunStatus
from retail_sim.repositories.runs import advance_run, create_run, finish_run, get_active_run
from retail_sim.repositories.stock import get_latest_snapshot_date
from retail_sim.simulation.day_runner import run_day

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from psycopg import Connection

    from retail_sim.simulation.day_runner import DayResult

_KOPECK = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class PeriodResult:
    run_id: int | None
    days: int
    receipts_created: int
    units_sold: int
    revenue: Decimal


def resume_start_date(conn: Connection[Any], date_from: date) -> date:
    # Незавершённый прогон важнее снимка: последний посчитанный день уже закоммичен.
    active = get_active_run(conn)
    if active is not None and active.last_done_date is not None:
        return active.last_done_date + timedelta(days=1)
    latest = get_latest_snapshot_date(conn)
    if latest is not None and latest >= date_from:
        # Этот день пересчитывается: S0 заменяет снимок, шаги снимают свои движения.
        return latest
    return date_from


def run_period(
    conn: Connection[Any],
    date_from: date,
    date_to: date,
    seed: int,
    *,
    journal: bool = True,
    on_day: Callable[[DayResult], None] | None = None,
) -> PeriodResult:
    """Каждый день коммитится отдельно. Прогресс журнала пишется следующей транзакцией."""
    if date_from > date_to:
        raise ValueError("date_from must be on or before date_to")

    run_id: int | None = None
    if journal:
        with conn.transaction():
            run_id = create_run(conn, date_from, date_to, seed)

    receipts_created = 0
    units_sold = 0
    revenue = Decimal("0.00")
    days = 0
    day = date_from
    try:
        while day <= date_to:
            result = run_day(conn, day, seed)
            if journal:
                assert run_id is not None
                with conn.transaction():
                    advance_run(conn, run_id, day)
            if on_day is not None:
                on_day(result)
            receipts_created += result.sales.receipts_created
            units_sold += result.sales.units_sold
            revenue += result.sales.revenue
            days += 1
            day += timedelta(days=1)
    except Exception as exc:
        _rollback_if_aborted(conn)
        if journal and run_id is not None:
            try:
                with conn.transaction():
                    finish_run(conn, run_id, RunStatus.FAILED, str(exc))
            except Exception:
                raise exc from None
        raise

    if journal:
        assert run_id is not None
        with conn.transaction():
            finish_run(conn, run_id, RunStatus.COMPLETED)
    return PeriodResult(
        run_id=run_id,
        days=days,
        receipts_created=receipts_created,
        units_sold=units_sold,
        revenue=revenue.quantize(_KOPECK),
    )


def _rollback_if_aborted(conn: Connection[Any]) -> None:
    # run_day уже откатил свой день. Полный rollback нужен только в аварийном состоянии,
    # иначе сбросится внешняя транзакция вызывающего кода.
    if conn.info.transaction_status == TransactionStatus.INERROR:
        conn.rollback()
