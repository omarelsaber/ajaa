"""
src/ajaa/db/backup.py

Transactionally consistent SQLite WAL backup utility (PRD §29.4 / §40.1).

Uses SQLite's `VACUUM INTO` to produce a clean, defragmented, consistent snapshot
of ajaa.db into the user data `backups/` directory without locking readers or writers.
Enforces 14-day retention by pruning older backups.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlalchemy as sa

from ajaa.config import get_settings
from ajaa.db.session import get_engine


def perform_backup(retention_days: int = 14) -> Path:
    """
    Create an online transactionally consistent backup using SQLite VACUUM INTO.
    Prune backups older than retention_days.
    Returns path to the newly created backup file.
    """
    settings = get_settings()
    backups_dir = settings.data_dir / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_file = backups_dir / f"ajaa_{timestamp}.db"
    if backup_file.exists():
        backup_file.unlink()

    engine = get_engine()
    with engine.connect() as conn:
        escaped_path = str(backup_file.resolve()).replace("'", "''")
        conn.execute(sa.text(f"VACUUM INTO '{escaped_path}'"))

    # Enforce retention policy
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    for f in backups_dir.glob("ajaa_*.db"):
        if f.is_file() and f != backup_file:
            pruned = False
            parts = f.stem.split("_")
            if len(parts) >= 2 and len(parts[1]) == 8 and parts[1].isdigit():
                try:
                    file_date = datetime.strptime(parts[1], "%Y%m%d").replace(tzinfo=timezone.utc)
                    if file_date < cutoff:
                        f.unlink()
                        pruned = True
                except Exception:
                    pass

            if not pruned:
                mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    try:
                        f.unlink()
                    except Exception:
                        pass

    return backup_file
