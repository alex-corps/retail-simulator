from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from retail_sim.cli import (
    build_parser,
    handle_replenish_run,
    handle_sales_run,
    handle_simulate,
    main,
)
from retail_sim.simulation.day_runner import DayResult
from retail_sim.simulation.period_runner import PeriodResult
from retail_sim.steps.s1_supplier import SupplierResult
from retail_sim.steps.s2_assortment import AssortmentResult
from retail_sim.steps.s3_replenish import ReplenishResult
from retail_sim.steps.s4_sales import SalesResult


def test_build_parser_requires_subcommand() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_build_parser_db_migrate_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args(["db", "migrate"])
    assert args.subcommand == "db"
    assert args.db_command == "migrate"
    assert args.migrations_dir is None


def test_build_parser_assortment_build() -> None:
    parser = build_parser()
    args = parser.parse_args(["assortment", "build", "--date", "2026-06-01"])
    assert args.subcommand == "assortment"
    assert args.assortment_command == "build"
    assert args.date == date(2026, 6, 1)


def test_build_parser_assortment_optimize_store_ids() -> None:
    parser = build_parser()
    args = parser.parse_args(["assortment", "optimize", "--store-id", "3", "8"])
    assert args.assortment_command == "optimize"
    assert args.store_id == [3, 8]
    assert args.all is False


def test_build_parser_assortment_optimize_requires_a_target() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["assortment", "optimize"])


def test_build_parser_supply_run() -> None:
    parser = build_parser()
    args = parser.parse_args(["supply", "run", "--date", "2026-06-01"])
    assert args.subcommand == "supply"
    assert args.supply_command == "run"
    assert args.date == date(2026, 6, 1)


def test_build_parser_replenish_run() -> None:
    parser = build_parser()
    args = parser.parse_args(["replenish", "run", "--date", "2026-06-03"])
    assert args.subcommand == "replenish"
    assert args.replenish_command == "run"
    assert args.date == date(2026, 6, 3)


def test_handle_replenish_run_step_order(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[str] = []

    class _Conn:
        def transaction(self) -> nullcontext[None]:
            return nullcontext()

    @contextmanager
    def fake_connection(_settings: object) -> Iterator[_Conn]:
        yield _Conn()

    def opening(_conn: object, _day: date) -> str:
        calls.append("s0")
        return "stock"

    def rollback(_conn: object, _day: date, stock: object) -> int:
        calls.append("rollback")
        assert stock == "stock"
        return 0

    def supplier(_conn: object, _day: date, _stock: object) -> SupplierResult:
        calls.append("s1")
        return SupplierResult(False, 1, 2, 3)

    def assortment(_conn: object, _day: date, _stock: object, seed: int) -> AssortmentResult:
        calls.append("s2")
        assert seed == 7
        return AssortmentResult(0, 0, 0)

    def replenish(_conn: object, _day: date, _stock: object) -> ReplenishResult:
        calls.append("s3")
        return ReplenishResult(1, 2, 3, 4)

    monkeypatch.setattr("retail_sim.cli.get_settings", lambda: SimpleNamespace(seed=7))
    monkeypatch.setattr("retail_sim.cli.get_connection", fake_connection)
    monkeypatch.setattr("retail_sim.cli.run_opening_stock", opening)
    monkeypatch.setattr("retail_sim.cli.rollback_replenish", rollback)
    monkeypatch.setattr("retail_sim.cli.run_supplier", supplier)
    monkeypatch.setattr("retail_sim.cli.run_assortment", assortment)
    monkeypatch.setattr("retail_sim.cli.run_replenish", replenish)

    code = handle_replenish_run(argparse.Namespace(date=date(2026, 6, 1)))

    assert code == 0
    assert calls == ["s0", "rollback", "s1", "s2", "s3"]
    assert "Replenishment: 1 store(s), 2 SKU line(s), 3 unit(s), 4 short SKU(s)." in (
        capsys.readouterr().out
    )


def test_build_parser_sales_run() -> None:
    parser = build_parser()
    args = parser.parse_args(["sales", "run", "--date", "2026-06-03"])
    assert args.subcommand == "sales"
    assert args.sales_command == "run"
    assert args.date == date(2026, 6, 3)


def test_handle_sales_run_prints_day_result(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Conn:
        pass

    @contextmanager
    def fake_connection(_settings: object) -> Iterator[_Conn]:
        yield _Conn()

    def run_day(_conn: object, day: date, seed: int) -> DayResult:
        assert day == date(2026, 6, 1)
        assert seed == 7
        return DayResult(
            day=day,
            supplier=SupplierResult(False, 1, 2, 3),
            assortment=AssortmentResult(0, 0, 0),
            replenish=ReplenishResult(1, 2, 3, 4),
            sales=SalesResult(1, 2, 3, 4, Decimal("10.00")),
        )

    monkeypatch.setattr("retail_sim.cli.get_settings", lambda: SimpleNamespace(seed=7))
    monkeypatch.setattr("retail_sim.cli.get_connection", fake_connection)
    monkeypatch.setattr("retail_sim.cli.run_day", run_day)

    code = handle_sales_run(argparse.Namespace(date=date(2026, 6, 1)))

    assert code == 0
    output = capsys.readouterr().out
    assert "Replenishment: 1 store(s), 2 SKU line(s), 3 unit(s), 4 short SKU(s)." in output
    assert "Sales: 1 store(s), 2 receipt(s), 3 line(s), 4 unit(s), 10.00 RUB." in output


def test_main_dispatches_sales_run(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[date] = []

    def handler(args: argparse.Namespace) -> int:
        seen.append(args.date)
        return 0

    monkeypatch.setattr("retail_sim.cli.handle_sales_run", handler)
    assert main(["sales", "run", "--date", "2026-06-03"]) == 0
    assert seen == [date(2026, 6, 3)]


def test_main_dispatches_replenish_run(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[date] = []

    def handler(args: argparse.Namespace) -> int:
        seen.append(args.date)
        return 0

    monkeypatch.setattr("retail_sim.cli.handle_replenish_run", handler)
    assert main(["replenish", "run", "--date", "2026-06-03"]) == 0
    assert seen == [date(2026, 6, 3)]


def test_build_parser_simulate() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["simulate", "--from", "2026-06-01", "--to", "2026-06-07", "--resume", "--no-journal"]
    )
    assert args.subcommand == "simulate"
    assert args.date_from == date(2026, 6, 1)
    assert args.date_to == date(2026, 6, 7)
    assert args.resume is True
    assert args.no_journal is True


def test_build_parser_simulate_requires_dates() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["simulate", "--from", "2026-06-01"])


def test_handle_simulate_prints_period(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Conn:
        pass

    @contextmanager
    def fake_connection(_settings: object) -> Iterator[_Conn]:
        yield _Conn()

    def run_period(
        _conn: object,
        date_from: date,
        date_to: date,
        seed: int,
        *,
        journal: bool,
        on_day: object,
    ) -> PeriodResult:
        assert date_from == date(2026, 6, 1)
        assert date_to == date(2026, 6, 7)
        assert seed == 7
        assert journal is False
        assert on_day is not None
        on_day(
            DayResult(
                day=date_from,
                supplier=SupplierResult(True, 1, 1, 1000),
                assortment=AssortmentResult(1, 0, 0),
                replenish=ReplenishResult(1, 1, 4, 0),
                sales=SalesResult(1, 2, 3, 4, Decimal("10.50")),
            )
        )
        return PeriodResult(None, 7, 2, 4, Decimal("10.50"))

    monkeypatch.setattr("retail_sim.cli.get_settings", lambda: SimpleNamespace(seed=7))
    monkeypatch.setattr("retail_sim.cli.get_connection", fake_connection)
    monkeypatch.setattr("retail_sim.cli.run_period", run_period)

    code = handle_simulate(
        argparse.Namespace(
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 7),
            resume=False,
            no_journal=True,
        )
    )

    assert code == 0
    output = capsys.readouterr().out
    assert "2026-06-01: 2 receipt(s), 4 unit(s), 10.50 RUB." in output
    assert "Period 2026-06-01..2026-06-07: 7 day(s), 2 receipt(s), 4 unit(s), 10.50 RUB." in (
        output
    )


def test_handle_simulate_resume_shifts_the_start(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    seen: dict[str, date] = {}

    class _Conn:
        pass

    @contextmanager
    def fake_connection(_settings: object) -> Iterator[_Conn]:
        yield _Conn()

    def resume(_conn: object, date_from: date) -> date:
        assert date_from == date(2026, 6, 1)
        return date(2026, 6, 4)

    def run_period(
        _conn: object,
        date_from: date,
        date_to: date,
        _seed: int,
        *,
        journal: bool,
        on_day: object,
    ) -> PeriodResult:
        seen["from"] = date_from
        seen["to"] = date_to
        assert journal is True
        assert on_day is not None
        return PeriodResult(3, 4, 0, 0, Decimal("0.00"))

    monkeypatch.setattr("retail_sim.cli.get_settings", lambda: SimpleNamespace(seed=7))
    monkeypatch.setattr("retail_sim.cli.get_connection", fake_connection)
    monkeypatch.setattr("retail_sim.cli.resume_start_date", resume)
    monkeypatch.setattr("retail_sim.cli.run_period", run_period)

    code = handle_simulate(
        argparse.Namespace(
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 7),
            resume=True,
            no_journal=False,
        )
    )

    assert code == 0
    assert seen == {"from": date(2026, 6, 4), "to": date(2026, 6, 7)}
    assert "Period 2026-06-04..2026-06-07:" in capsys.readouterr().out


def test_handle_simulate_resume_past_the_end_does_not_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class _Conn:
        pass

    @contextmanager
    def fake_connection(_settings: object) -> Iterator[_Conn]:
        yield _Conn()

    def resume(_conn: object, _date_from: date) -> date:
        return date(2026, 6, 8)

    def run_period(*_args: object, **_kwargs: object) -> PeriodResult:
        raise AssertionError("period must not start")

    monkeypatch.setattr("retail_sim.cli.get_settings", lambda: SimpleNamespace(seed=7))
    monkeypatch.setattr("retail_sim.cli.get_connection", fake_connection)
    monkeypatch.setattr("retail_sim.cli.resume_start_date", resume)
    monkeypatch.setattr("retail_sim.cli.run_period", run_period)

    code = handle_simulate(
        argparse.Namespace(
            date_from=date(2026, 6, 1),
            date_to=date(2026, 6, 7),
            resume=True,
            no_journal=False,
        )
    )

    assert code == 0
    assert "Nothing to simulate: 2026-06-08 is after 2026-06-07." in capsys.readouterr().out


def test_main_dispatches_simulate(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[date] = []

    def handler(args: argparse.Namespace) -> int:
        seen.append(args.date_from)
        seen.append(args.date_to)
        return 0

    monkeypatch.setattr("retail_sim.cli.handle_simulate", handler)
    assert main(["simulate", "--from", "2026-06-01", "--to", "2026-06-03"]) == 0
    assert seen == [date(2026, 6, 1), date(2026, 6, 3)]


def test_build_parser_db_migrate_custom_dir() -> None:
    parser = build_parser()
    args = parser.parse_args(["db", "migrate", "--migrations-dir", "custom/path"])
    assert args.subcommand == "db"
    assert args.db_command == "migrate"
    assert args.migrations_dir == Path("custom/path")
