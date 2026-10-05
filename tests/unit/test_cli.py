from __future__ import annotations

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


def test_build_parser_db_migrate_custom_dir() -> None:
    parser = build_parser()
    args = parser.parse_args(["db", "migrate", "--migrations-dir", "custom/path"])
    assert args.subcommand == "db"
    assert args.db_command == "migrate"
    assert args.migrations_dir == Path("custom/path")
