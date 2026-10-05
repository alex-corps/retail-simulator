from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Protocol

from retail_sim.db.connection import get_connection
from retail_sim.domain.enums import RunStatus
from retail_sim.repositories.runs import finish_run, get_active_run, get_run, list_running_runs
from retail_sim.simulation.period_runner import run_period

if TYPE_CHECKING:
    from datetime import date

    from retail_sim.config import Settings

ALREADY_RUNNING = "Расчёт уже выполняется"
ABORT_WHILE_LOCAL = "Расчёт ещё выполняется в этой панели"
ABORT_MESSAGE = "Прогон прерван панелью"


class JobError(Exception):
    pass


class PeriodJobHandle(Protocol):
    def is_alive(self) -> bool: ...

    def start(self, date_from: date, date_to: date) -> None: ...

    def abort_orphaned(self, run_id: int) -> None: ...

    def abort_stuck_runs(self) -> None: ...

    def last_error(self) -> str | None: ...


class PeriodJob:
    """Один фоновый прогон на процесс. Соединение потока не отдаётся запросам."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._error: str | None = None

    def is_alive(self) -> bool:
        with self._lock:
            return self._running

    def last_error(self) -> str | None:
        with self._lock:
            return self._error

    def join(self, timeout: float | None = None) -> None:
        with self._lock:
            thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def start(self, date_from: date, date_to: date) -> None:
        with self._lock:
            if self._running:
                raise JobError(ALREADY_RUNNING)
            with get_connection(self._settings) as conn:
                if get_active_run(conn) is not None:
                    raise JobError(ALREADY_RUNNING)
            self._error = None
            self._running = True
            thread = threading.Thread(
                target=self._run,
                args=(date_from, date_to),
                name="retail-sim-period",
                daemon=True,
            )
            self._thread = thread
        try:
            thread.start()
        except Exception:
            with self._lock:
                self._running = False
            raise

    def abort_orphaned(self, run_id: int) -> None:
        # Живой поток этой панели не прерываем: дни уже коммитятся по одному.
        with self._lock:
            if self._running:
                raise JobError(ABORT_WHILE_LOCAL)
            # SELECT и UPDATE в одной транзакции, иначе закрытие соединения откатит запись.
            with get_connection(self._settings) as conn, conn.transaction():
                run = get_run(conn, run_id)
                if run is None:
                    raise JobError("Прогон не найден")
                if run.status != RunStatus.RUNNING:
                    raise JobError("Прогон уже завершён")
                finish_run(conn, run_id, RunStatus.FAILED, ABORT_MESSAGE)

    def abort_stuck_runs(self) -> None:
        # Несколько строк running снимаются одним нажатием, пока эта панель сама не считает.
        with self._lock:
            if self._running:
                raise JobError(ABORT_WHILE_LOCAL)
            with get_connection(self._settings) as conn, conn.transaction():
                runs = list_running_runs(conn)
                if not runs:
                    raise JobError("Прогон уже завершён")
                for run in runs:
                    finish_run(conn, run.id, RunStatus.FAILED, ABORT_MESSAGE)

    def _run(self, date_from: date, date_to: date) -> None:
        try:
            with get_connection(self._settings) as conn:
                run_period(
                    conn,
                    date_from,
                    date_to,
                    self._settings.seed,
                    journal=True,
                )
        except Exception as exc:
            with self._lock:
                self._error = str(exc)
        finally:
            with self._lock:
                self._running = False
