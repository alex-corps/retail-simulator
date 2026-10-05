from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from psycopg.rows import class_row

from retail_sim.domain.enums import RunStatus
from retail_sim.domain.models import SimulationRun

if TYPE_CHECKING:
    from datetime import date

    from psycopg import Connection

_RUN_COLUMNS = """
    id,
    date_from,
    date_to,
    days_total,
    days_done,
    last_done_date,
    status,
    seed,
    error_message,
    started_at,
    finished_at
"""


def _as_run(row: SimulationRun) -> SimulationRun:
    return replace(row, status=RunStatus(str(row.status)))


def _fetch_runs(
    conn: Connection[Any],
    where_sql: str,
    params: tuple[Any, ...],
) -> list[SimulationRun]:
    with conn.cursor(row_factory=class_row(SimulationRun)) as cur:
        cur.execute(
            f"""
            SELECT {_RUN_COLUMNS}
            FROM simulation_runs
            {where_sql}
            """,
            params,
        )
        rows = cur.fetchall()
    return [_as_run(row) for row in rows]


class RunNotFoundError(Exception):
    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        super().__init__(f"Simulation run {run_id} does not exist")


def create_run(conn: Connection[Any], date_from: date, date_to: date, seed: int) -> int:
    days_total = (date_to - date_from).days + 1
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO simulation_runs (date_from, date_to, days_total, seed)
            VALUES (%(date_from)s, %(date_to)s, %(days_total)s, %(seed)s)
            RETURNING id
            """,
            {
                "date_from": date_from,
                "date_to": date_to,
                "days_total": days_total,
                "seed": seed,
            },
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("simulation_runs insert did not return an id")
    return int(row[0])


def advance_run(conn: Connection[Any], run_id: int, day: date) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE simulation_runs
            SET days_done = days_done + 1,
                last_done_date = %(day)s
            WHERE id = %(run_id)s
            """,
            {"run_id": run_id, "day": day},
        )
        if cur.rowcount != 1:
            raise RunNotFoundError(run_id)


def finish_run(
    conn: Connection[Any],
    run_id: int,
    status: RunStatus,
    error_message: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE simulation_runs
            SET status = %(status)s,
                error_message = %(error_message)s,
                finished_at = NOW()
            WHERE id = %(run_id)s
            """,
            {"run_id": run_id, "status": str(status), "error_message": error_message},
        )
        if cur.rowcount != 1:
            raise RunNotFoundError(run_id)


def get_run(conn: Connection[Any], run_id: int) -> SimulationRun | None:
    rows = _fetch_runs(conn, "WHERE id = %s", (run_id,))
    if not rows:
        return None
    return rows[0]


def list_runs(conn: Connection[Any], limit: int = 50) -> list[SimulationRun]:
    if limit <= 0:
        return []
    return _fetch_runs(
        conn,
        "ORDER BY started_at DESC, id DESC LIMIT %s",
        (limit,),
    )


def list_running_runs(conn: Connection[Any]) -> list[SimulationRun]:
    return _fetch_runs(
        conn,
        "WHERE status = %s ORDER BY started_at DESC, id DESC",
        (str(RunStatus.RUNNING),),
    )


def get_active_run(conn: Connection[Any]) -> SimulationRun | None:
    rows = list_running_runs(conn)
    if not rows:
        return None
    return rows[0]
