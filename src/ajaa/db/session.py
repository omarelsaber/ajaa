"""
src/ajaa/db/session.py

Database engine and session factory.

Design:
  - Sync SQLAlchemy (Spike V-11 decision)
  - WAL mode enabled on first connection for better read concurrency
  - Engine is a module-level singleton (one per process)
  - From async code: use run_in_executor(None, sync_function, *args)
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Generator

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy import event

from ajaa.db.models import Base

_engine: sa.Engine | None = None
_SessionFactory: orm.sessionmaker | None = None  # type: ignore[type-arg]


def _enable_wal(dbapi_connection: object, connection_record: object) -> None:
    """Enable WAL journal mode for better concurrent read performance."""
    cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")  # safe with WAL
    cursor.close()


def init_engine(db_path: Path) -> sa.Engine:
    """
    Initialize the database engine. Call once at startup from bootstrap.
    Safe to call multiple times (idempotent).
    """
    global _engine, _SessionFactory

    if _engine is not None:
        return _engine

    db_path.parent.mkdir(parents=True, exist_ok=True)

    _engine = sa.create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # Enable WAL mode on every new connection
    event.listen(_engine, "connect", _enable_wal)

    # Create tables if they don't exist
    Base.metadata.create_all(_engine)

    _SessionFactory = orm.sessionmaker(bind=_engine, expire_on_commit=False)

    return _engine


def get_engine() -> sa.Engine:
    """Return the initialized engine. Raises if init_engine() not called."""
    if _engine is None:
        raise RuntimeError(
            "Database engine not initialized. "
            "Call init_engine(db_path) at startup, or run 'ajaa init'."
        )
    return _engine


@contextmanager
def get_session() -> Generator[orm.Session, None, None]:
    """
    Context manager that yields a session and auto-commits/rolls back.

    Usage:
        with get_session() as session:
            session.add(fact)
            session.commit()

    From async code:
        await loop.run_in_executor(None, _sync_write_fact, fact_data)
    """
    if _SessionFactory is None:
        raise RuntimeError("Database not initialized. Call init_engine() first.")

    session = _SessionFactory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Dispose engine and reset singleton. For tests only."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None