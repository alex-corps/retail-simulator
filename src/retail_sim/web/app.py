from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from starlette.templating import Jinja2Templates

from retail_sim.db.connection import get_connection
from retail_sim.domain.enums import OptimizationFlag, RunStatus
from retail_sim.repositories.promo import insert_sale_period, list_sale_periods
from retail_sim.repositories.runs import get_active_run, list_runs
from retail_sim.repositories.stores import StoreNotFoundError, list_stores, set_optimization_flag
from retail_sim.web.forms import FormError, PromoForm, parse_date_range, parse_promo_form
from retail_sim.web.jobs import JobError, PeriodJob, PeriodJobHandle

if TYPE_CHECKING:
    from collections.abc import Sequence

    from starlette.responses import Response

    from retail_sim.config import Settings
    from retail_sim.domain.models import SalePeriod, SimulationRun, Store

_STATUS_LABELS: dict[str, str] = {
    RunStatus.RUNNING: "выполняется",
    RunStatus.COMPLETED: "завершён",
    RunStatus.FAILED: "ошибка",
}
_FLAG_LABELS: dict[int, str] = {
    int(OptimizationFlag.IDLE): "не запрашивалась",
    int(OptimizationFlag.REQUESTED): "запрошена",
    int(OptimizationFlag.COMPLETED): "выполнена",
}


@dataclass(frozen=True, slots=True)
class PanelData:
    stores: list[Store]
    periods: list[SalePeriod]
    runs: list[SimulationRun]
    active: SimulationRun | None


def template_dir() -> Path:
    resource = files("retail_sim.web").joinpath("templates")
    location = Path(str(resource))
    if location.is_dir():
        return location
    fallback = Path(__file__).resolve().parent / "templates"
    if fallback.is_dir():
        return fallback
    raise RuntimeError("panel templates are missing")


def load_panel(settings: Settings) -> PanelData:
    with get_connection(settings) as conn:
        return PanelData(
            stores=list_stores(conn),
            periods=list_sale_periods(conn),
            runs=list_runs(conn),
            active=get_active_run(conn),
        )


def add_promo(settings: Settings, form: PromoForm) -> None:
    with get_connection(settings) as conn, conn.transaction():
        if form.all_stores:
            store_ids = [store.id for store in list_stores(conn)]
        else:
            store_ids = list(form.store_ids)
        if not store_ids:
            raise FormError("Нет магазинов для периода распродажи")
        insert_sale_period(
            conn,
            form.date_from,
            form.date_to,
            form.price_factor,
            store_ids,
        )


def request_optimization(settings: Settings, store_ids: Sequence[int]) -> None:
    if not store_ids:
        raise FormError("Выберите хотя бы один магазин")
    with get_connection(settings) as conn, conn.transaction():
        for store_id in store_ids:
            set_optimization_flag(conn, store_id, OptimizationFlag.REQUESTED)


def _run_payload(run: SimulationRun) -> dict[str, object]:
    return {
        "id": run.id,
        "date_from": run.date_from.isoformat(),
        "date_to": run.date_to.isoformat(),
        "days_done": run.days_done,
        "days_total": run.days_total,
        "status_label": _STATUS_LABELS[run.status.value],
        "error_message": run.error_message,
    }


def _progress_text(
    current: SimulationRun | None,
    *,
    job_alive: bool,
    active: SimulationRun | None,
) -> str:
    if job_alive and active is None:
        return "Расчёт запускается…"
    if current is None:
        return "Расчёт не запущен."
    last = ""
    if current.last_done_date is not None:
        last = f" (последний день {current.last_done_date.isoformat()})"
    label = _STATUS_LABELS[current.status.value]
    return (
        f"{current.date_from.isoformat()} — {current.date_to.isoformat()}: "
        f"{current.days_done} / {current.days_total}, {label}{last}"
    )


def _status_payload(data: PanelData, job: PeriodJobHandle) -> dict[str, object]:
    current = data.active if data.active is not None else (data.runs[0] if data.runs else None)
    thread_error = job.last_error()
    run_error = current.error_message if current is not None else None
    if run_error:
        thread_error = None
    job_alive = job.is_alive()
    abort_run_id = data.active.id if data.active is not None and not job_alive else None
    return {
        "job_alive": job_alive,
        "start_blocked": job_alive or data.active is not None,
        "abort_run_id": abort_run_id,
        "progress": _progress_text(current, job_alive=job_alive, active=data.active),
        "error_message": run_error,
        "thread_error": thread_error,
        "runs": [_run_payload(run) for run in data.runs],
    }


def create_app(settings: Settings, job: PeriodJobHandle | None = None) -> FastAPI:
    period_job = job if job is not None else PeriodJob(settings)
    templates = Jinja2Templates(directory=template_dir())
    app = FastAPI(title="Retail simulator")

    def render(request: Request, error: str | None = None, status_code: int = 200) -> Response:
        data = load_panel(settings)
        status = _status_payload(data, period_job)
        return templates.TemplateResponse(
            request,
            "panel.html",
            {
                "error": error,
                "thread_error": status["thread_error"],
                "progress": status["progress"],
                "run_error": status["error_message"],
                "abort_run_id": status["abort_run_id"],
                "stores": data.stores,
                "periods": data.periods,
                "runs": data.runs,
                "start_blocked": status["start_blocked"],
                "status_labels": _STATUS_LABELS,
                "flag_labels": _FLAG_LABELS,
            },
            status_code=status_code,
        )

    @app.get("/")
    def index(request: Request) -> Response:
        return render(request)

    @app.get("/status")
    def run_status() -> dict[str, object]:
        return _status_payload(load_panel(settings), period_job)

    @app.post("/simulate")
    def start_period(
        request: Request,
        date_from: Annotated[str, Form()] = "",
        date_to: Annotated[str, Form()] = "",
    ) -> Response:
        try:
            period = parse_date_range(date_from, date_to)
            period_job.start(period.date_from, period.date_to)
        except (FormError, JobError) as exc:
            return render(request, str(exc), status_code=400)
        return RedirectResponse("/", status_code=303)

    @app.post("/promo")
    def create_promo(
        request: Request,
        date_from: Annotated[str, Form()] = "",
        date_to: Annotated[str, Form()] = "",
        factor: Annotated[str, Form()] = "",
        store_ids: Annotated[str, Form()] = "",
        all_stores: Annotated[str | None, Form()] = None,
    ) -> Response:
        try:
            form = parse_promo_form(
                date_from,
                date_to,
                factor,
                store_ids,
                all_stores=bool(all_stores),
            )
            add_promo(settings, form)
        except FormError as exc:
            return render(request, str(exc), status_code=400)
        except StoreNotFoundError as exc:
            return render(request, f"Магазин {exc.store_id} не найден", status_code=400)
        except ValueError:
            return render(request, "Ошибка записи периода распродажи", status_code=400)
        return RedirectResponse("/", status_code=303)

    @app.post("/optimize")
    def optimize(
        request: Request,
        store_id: Annotated[list[int] | None, Form()] = None,
    ) -> Response:
        chosen = store_id or []
        if not chosen:
            return render(request, "Выберите хотя бы один магазин", status_code=400)
        try:
            request_optimization(settings, chosen)
        except FormError as exc:
            return render(request, str(exc), status_code=400)
        except StoreNotFoundError as exc:
            return render(request, f"Магазин {exc.store_id} не найден", status_code=400)
        return RedirectResponse("/", status_code=303)

    @app.post("/runs/abort")
    def abort_stuck(request: Request) -> Response:
        try:
            period_job.abort_stuck_runs()
        except JobError as exc:
            return render(request, str(exc), status_code=400)
        return RedirectResponse("/", status_code=303)

    @app.post("/runs/{run_id}/abort")
    def abort_run(request: Request, run_id: int) -> Response:
        try:
            period_job.abort_orphaned(run_id)
        except JobError as exc:
            return render(request, str(exc), status_code=400)
        return RedirectResponse("/", status_code=303)

    return app
