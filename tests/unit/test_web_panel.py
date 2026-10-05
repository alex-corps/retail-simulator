from __future__ import annotations

import threading
from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from retail_sim.config import Settings
from retail_sim.domain.enums import OptimizationFlag, RunStatus
from retail_sim.domain.models import SalePeriod, SimulationRun, Store
from retail_sim.web.app import PanelData, create_app
from retail_sim.web.forms import PromoForm
from retail_sim.web.jobs import (
    ABORT_MESSAGE,
    JobError,
    PeriodJob,
)

_STARTED = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)


class _Conn:
    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def transaction(self) -> _Conn:
        return self


class _Job:
    def __init__(self, *, alive: bool = False) -> None:
        self.alive = alive
        self.started: list[tuple[date, date]] = []
        self.aborted: list[int] = []
        self.error: str | None = None

    def is_alive(self) -> bool:
        return self.alive

    def start(self, date_from: date, date_to: date) -> None:
        if self.alive:
            raise JobError("Расчёт уже выполняется")
        self.started.append((date_from, date_to))

    def abort_orphaned(self, run_id: int) -> None:
        if self.alive:
            raise JobError("Расчёт ещё выполняется в этой панели")
        self.aborted.append(run_id)

    def abort_stuck_runs(self) -> None:
        if self.alive:
            raise JobError("Расчёт ещё выполняется в этой панели")
        self.aborted.append(0)

    def last_error(self) -> str | None:
        return self.error


def _settings() -> Settings:
    return Settings(database_url="postgresql://postgres:postgres@localhost/retail_sim", seed=1)


def _store() -> Store:
    return Store(
        id=3,
        storage_location_id=1,
        warehouse_id=1,
        name="Север",
        avg_receipts_per_day=Decimal("10"),
        sku_capacity=100,
        open_from=time(10, 0),
        open_to=time(21, 0),
        optimization_flag=OptimizationFlag.IDLE,
    )


def _run(status: RunStatus = RunStatus.COMPLETED, *, run_id: int = 5) -> SimulationRun:
    return SimulationRun(
        id=run_id,
        date_from=date(2026, 6, 1),
        date_to=date(2026, 6, 2),
        days_total=2,
        days_done=2,
        last_done_date=date(2026, 6, 2),
        status=status,
        seed=1,
        error_message="сбой дня" if status == RunStatus.FAILED else None,
        started_at=_STARTED,
        finished_at=_STARTED,
    )


def _panel(data: PanelData | None = None) -> PanelData:
    if data is not None:
        return data
    return PanelData(
        stores=[_store()],
        periods=[
            SalePeriod(
                id=1,
                date_from=date(2026, 6, 1),
                date_to=date(2026, 6, 7),
                price_factor=Decimal("0.8000"),
                store_ids=(3, 8),
            )
        ],
        runs=[_run()],
        active=None,
    )


def _client(
    monkeypatch: pytest.MonkeyPatch,
    job: _Job,
    data: PanelData | None = None,
) -> TestClient:
    panel = _panel(data)
    monkeypatch.setattr("retail_sim.web.app.load_panel", lambda _settings: panel)
    return TestClient(create_app(_settings(), job))


def test_index_renders_the_four_blocks(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(monkeypatch, _Job())
    response = client.get("/")
    assert response.status_code == 200
    page = response.text
    assert "Расчёт за период" in page
    assert "Периоды распродаж" in page
    assert "Оптимизация ассортимента" in page
    assert "Проведённые расчёты" in page
    assert "Север" in page
    assert "0 — не запрашивалась" in page
    assert "0.8000" in page
    assert "3, 8" in page
    assert "завершён" in page
    assert "2 / 2" in page
    assert 'http-equiv="refresh"' not in page
    assert "disabled>Запустить расчёт" not in page


def test_invalid_factor_is_shown_and_does_not_save(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[PromoForm] = []

    def add_promo(_settings: Settings, form: PromoForm) -> None:
        calls.append(form)

    monkeypatch.setattr("retail_sim.web.app.add_promo", add_promo)
    client = _client(monkeypatch, _Job())
    response = client.post(
        "/promo",
        data={
            "date_from": "2026-06-01",
            "date_to": "2026-06-07",
            "factor": "1,5",
            "store_ids": "3",
        },
    )
    assert response.status_code == 400
    assert "больше 0 и меньше 1" in response.text
    assert "Периоды распродаж" in response.text
    assert calls == []


def test_promo_post_calls_add_with_parsed_factor(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[PromoForm] = []

    def add_promo(_settings: Settings, form: PromoForm) -> None:
        calls.append(form)

    monkeypatch.setattr("retail_sim.web.app.add_promo", add_promo)
    client = _client(monkeypatch, _Job())
    response = client.post(
        "/promo",
        data={
            "date_from": "2026-06-01",
            "date_to": "2026-06-07",
            "factor": "0,8",
            "store_ids": "",
            "all_stores": "on",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert len(calls) == 1
    assert calls[0].all_stores is True
    assert calls[0].price_factor == Decimal("0.8000")


def test_optimize_post_sets_the_requested_flag_for_chosen_stores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[int]] = []

    def request_optimization(_settings: Settings, store_ids: Sequence[int]) -> None:
        calls.append(list(store_ids))

    monkeypatch.setattr("retail_sim.web.app.request_optimization", request_optimization)
    client = _client(monkeypatch, _Job())
    empty = client.post("/optimize", data={})
    assert empty.status_code == 400
    assert "хотя бы один" in empty.text
    assert calls == []

    saved = client.post(
        "/optimize",
        data={"store_id": ["3", "8"]},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert calls == [[3, 8]]


def test_second_start_does_not_launch_another_period(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _Job(alive=True)
    client = _client(monkeypatch, job)
    response = client.post(
        "/simulate",
        data={"date_from": "2026-06-01", "date_to": "2026-06-03"},
    )
    assert response.status_code == 400
    assert "уже выполняется" in response.text
    assert job.started == []


def test_start_redirects_when_the_job_accepts_the_range(monkeypatch: pytest.MonkeyPatch) -> None:
    job = _Job()
    client = _client(monkeypatch, job)
    response = client.post(
        "/simulate",
        data={"date_from": "2026-06-03", "date_to": "2026-06-01"},
    )
    assert response.status_code == 400
    assert job.started == []

    started = client.post(
        "/simulate",
        data={"date_from": "2026-06-01", "date_to": "2026-06-03"},
        follow_redirects=False,
    )
    assert started.status_code == 303
    assert job.started == [(date(2026, 6, 1), date(2026, 6, 3))]


def test_running_page_polls_status_and_hides_abort_while_the_local_job_is_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = _run(RunStatus.RUNNING, run_id=9)
    data = PanelData(stores=[], periods=[], runs=[run], active=run)
    job = _Job(alive=True)
    client = _client(monkeypatch, job, data)
    page = client.get("/").text
    assert 'http-equiv="refresh"' not in page
    assert 'fetch("/status")' in page
    assert 'action="/runs/abort" hidden' in page
    assert "disabled>Запустить расчёт" in page

    aborted = client.post("/runs/9/abort")
    assert aborted.status_code == 400
    assert 'http-equiv="refresh"' not in aborted.text
    assert job.aborted == []

    status = client.get("/status").json()
    assert status["start_blocked"] is True
    assert status["abort_run_id"] is None
    assert "2 / 2" in status["progress"]


def test_orphaned_run_can_be_marked_interrupted(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _run(RunStatus.RUNNING, run_id=9)
    data = PanelData(stores=[], periods=[], runs=[run], active=run)
    job = _Job()
    client = _client(monkeypatch, job, data)
    page = client.get("/").text
    assert "Пометить прерванным" in page
    assert 'action="/runs/abort"' in page
    assert "другом терминале" in page
    status = client.get("/status").json()
    assert status["abort_run_id"] == 9
    assert status["runs"][0]["days_done"] == 2

    response = client.post("/runs/abort", follow_redirects=False)
    assert response.status_code == 303
    assert job.aborted == [0]


def test_period_job_rejects_a_second_start_and_an_active_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def run_period(*_args: object, **_kwargs: object) -> None:
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr("retail_sim.web.jobs.get_connection", lambda _settings: _Conn())
    monkeypatch.setattr("retail_sim.web.jobs.get_active_run", lambda _conn: None)
    monkeypatch.setattr("retail_sim.web.jobs.run_period", run_period)
    job = PeriodJob(_settings())
    job.start(date(2026, 6, 1), date(2026, 6, 2))
    assert entered.wait(2)
    with pytest.raises(JobError, match="уже выполняется"):
        job.start(date(2026, 6, 3), date(2026, 6, 4))
    release.set()
    job.join(2)
    assert job.is_alive() is False

    monkeypatch.setattr("retail_sim.web.jobs.get_active_run", lambda _conn: object())
    with pytest.raises(JobError, match="уже выполняется"):
        job.start(date(2026, 6, 3), date(2026, 6, 4))
    assert job.is_alive() is False


def test_abort_orphaned_marks_only_a_running_row_without_a_local_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finished: list[tuple[int, RunStatus, str | None]] = []
    run = _run(RunStatus.RUNNING, run_id=4)

    def finish(
        _conn: object,
        run_id: int,
        status: RunStatus,
        error_message: str | None = None,
    ) -> None:
        finished.append((run_id, status, error_message))

    monkeypatch.setattr("retail_sim.web.jobs.get_connection", lambda _settings: _Conn())
    monkeypatch.setattr("retail_sim.web.jobs.get_run", lambda _conn, run_id: run)
    monkeypatch.setattr("retail_sim.web.jobs.finish_run", finish)
    job = PeriodJob(_settings())
    job.abort_orphaned(4)
    assert finished == [(4, RunStatus.FAILED, ABORT_MESSAGE)]

    other = _run(RunStatus.RUNNING, run_id=2)
    monkeypatch.setattr("retail_sim.web.jobs.list_running_runs", lambda _conn: [run, other])
    job.abort_stuck_runs()
    assert finished[1:] == [
        (4, RunStatus.FAILED, ABORT_MESSAGE),
        (2, RunStatus.FAILED, ABORT_MESSAGE),
    ]

    monkeypatch.setattr("retail_sim.web.jobs.get_run", lambda _conn, run_id: None)
    with pytest.raises(JobError, match="не найден"):
        job.abort_orphaned(4)

    done = _run(RunStatus.COMPLETED, run_id=4)
    monkeypatch.setattr("retail_sim.web.jobs.get_run", lambda _conn, run_id: done)
    with pytest.raises(JobError, match="завершён"):
        job.abort_orphaned(4)
    assert len(finished) == 3
