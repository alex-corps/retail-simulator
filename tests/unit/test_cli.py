from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from retail_sim.cli import build_parser, handle_replenish_run, main
from retail_sim.steps.s1_supplier import SupplierResult
from retail_sim.steps.s2_assortment import AssortmentResult
from retail_sim.steps.s3_replenish import ReplenishResult


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


def test_main_dispatches_replenish_run(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[date] = []

    def handler(args: argparse.Namespace) -> int:
        seen.append(args.date)
        return 0

    monkeypatch.setattr("retail_sim.cli.handle_replenish_run", handler)
    assert main(["replenish", "run", "--date", "2026-06-03"]) == 0
    assert seen == [date(2026, 6, 3)]


def test_build_parser_db_migrate_custom_dir() -> None:
    parser = build_parser()
    args = parser.parse_args(["db", "migrate", "--migrations-dir", "custom/path"])
    assert args.subcommand == "db"
    assert args.db_command == "migrate"
    assert args.migrations_dir == Path("custom/path")
