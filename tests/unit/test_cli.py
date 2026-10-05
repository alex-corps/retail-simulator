from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from retail_sim.cli import build_parser


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


def test_build_parser_db_migrate_custom_dir() -> None:
    parser = build_parser()
    args = parser.parse_args(["db", "migrate", "--migrations-dir", "custom/path"])
    assert args.subcommand == "db"
    assert args.db_command == "migrate"
    assert args.migrations_dir == Path("custom/path")
