from __future__ import annotations

from pathlib import Path

import pytest

from retail_sim.db.migrate import discover_migration_files


def test_discover_migration_files_sorts_correctly(tmp_path: Path) -> None:
    (tmp_path / "0002_second.sql").write_text("SELECT 2;", encoding="utf-8")
    (tmp_path / "0001_first.sql").write_text("SELECT 1;", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("ignore me", encoding="utf-8")

    files = discover_migration_files(tmp_path)
    assert len(files) == 2
    assert files[0].name == "0001_first.sql"
    assert files[1].name == "0002_second.sql"


def test_discover_migration_files_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError):
        discover_migration_files(missing)


def test_discover_migration_files_not_a_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "not_a_dir.sql"
    file_path.write_text("SELECT 1;", encoding="utf-8")
    with pytest.raises(NotADirectoryError):
        discover_migration_files(file_path)
