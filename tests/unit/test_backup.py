"""
tests/unit/test_backup.py

Unit tests for SQLite VACUUM INTO backup and 14-day retention (PRD §29.4).
"""
from pathlib import Path
from datetime import datetime, timedelta, timezone
import os
import pytest

from ajaa.config import reload_settings
from ajaa.db.backup import perform_backup
from ajaa.db.session import init_engine, reset_engine
from ajaa.db.repositories import candidate as candidate_repo


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    db_file = data_dir / "db" / "ajaa.db"
    monkeypatch.setenv("AJAA_DATA_DIR", str(data_dir))
    reload_settings()
    init_engine(db_file)
    yield data_dir
    reset_engine()
    reload_settings()


def test_perform_backup_creates_consistent_db(fresh_db: Path):
    candidate_repo.create(display_name="BackupTester")

    backup_path = perform_backup(retention_days=14)
    assert backup_path.exists()
    assert backup_path.stat().st_size > 0
    assert backup_path.name.startswith("ajaa_")
    assert backup_path.suffix == ".db"


def test_perform_backup_retention_pruning(fresh_db: Path):
    backups_dir = fresh_db / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    # Create an old fake backup
    old_file = backups_dir / "ajaa_20200101_000000.db"
    old_file.write_text("old")
    past_time = (datetime.now(timezone.utc) - timedelta(days=20)).timestamp()
    os.utime(str(old_file), (past_time, past_time))

    new_backup = perform_backup(retention_days=14)

    assert new_backup.exists()
    assert not old_file.exists(), "Old backup outside retention window must be pruned"
