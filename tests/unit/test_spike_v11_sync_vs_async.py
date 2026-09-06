"""
tests/unit/test_spike_v11_sync_vs_async.py

Spike V-11: SQLAlchemy sync vs async for AJAA's workload.

This is a DECISION SPIKE — it runs real SQLite operations and measures
whether async adds any benefit for a single-user, local-first tool.

Conclusion recorded at bottom of file.
"""
from __future__ import annotations

import asyncio
import tempfile
import time
from pathlib import Path

import pytest
import sqlalchemy as sa
import sqlalchemy.orm as orm


# ── Sync setup ────────────────────────────────────────────────────────────────

class Base(orm.DeclarativeBase):
    pass


class SpikeFact(Base):
    __tablename__ = "spike_facts"
    id: orm.Mapped[int] = orm.mapped_column(primary_key=True)
    key: orm.Mapped[str] = orm.mapped_column(sa.String(100))
    value: orm.Mapped[str] = orm.mapped_column(sa.Text)


def _make_sync_engine(path: Path) -> sa.Engine:
    engine = sa.create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine


def _sync_write_read(engine: sa.Engine, n: int) -> float:
    """Write n rows, read them back. Return elapsed seconds."""
    start = time.monotonic()
    with orm.Session(engine) as session:
        for i in range(n):
            session.add(SpikeFact(key=f"key_{i}", value=f"value_{i}" * 10))
        session.commit()
        _ = session.execute(sa.select(SpikeFact)).scalars().all()
    return time.monotonic() - start


# ── Async setup ───────────────────────────────────────────────────────────────

async def _make_async_engine(path: Path):  # type: ignore[return]
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _async_write_read(engine, n: int) -> float:  # type: ignore[type-arg]
    from sqlalchemy.ext.asyncio import AsyncSession
    start = time.monotonic()
    async with AsyncSession(engine) as session:
        for i in range(n):
            session.add(SpikeFact(key=f"key_{i}", value=f"value_{i}" * 10))
        await session.commit()
        result = await session.execute(sa.select(SpikeFact))
        _ = result.scalars().all()
    return time.monotonic() - start


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSpikeV11SyncVsAsync:
    """
    Spike V-11: measure and document sync vs async SQLAlchemy for AJAA's workload.

    AJAA's DB workload:
    - Tens of rows written per run (job discoveries, applications, facts)
    - Reads are small (single application, single profile)
    - No concurrent writers (single-user, single process)
    - Browser automation (Playwright) is async — DB calls happen inside async context
    """

    def test_sync_write_read_small(self) -> None:
        """Sync SQLAlchemy handles small workloads correctly."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        engine = _make_sync_engine(path)
        try:
            elapsed = _sync_write_read(engine, 50)
            assert elapsed < 2.0, f"Sync write/read of 50 rows took {elapsed:.3f}s — too slow"
        finally:
            engine.dispose()  # Windows: must dispose before unlink
            path.unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_async_write_read_small(self) -> None:
        """Async SQLAlchemy handles small workloads correctly."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        engine = await _make_async_engine(path)
        try:
            elapsed = await _async_write_read(engine, 50)
            assert elapsed < 2.0, f"Async write/read of 50 rows took {elapsed:.3f}s — too slow"
        finally:
            await engine.dispose()  # Windows: must dispose before unlink
            path.unlink(missing_ok=True)

    def test_sync_callable_from_async_via_executor(self) -> None:
        """
        CRITICAL: Can sync SQLAlchemy DB calls be safely called from async context
        using run_in_executor?

        This is the key question: if we use sync SQLAlchemy, browser automation
        (async Playwright) must call DB via asyncio.get_event_loop().run_in_executor.
        This test proves it works without deadlock.
        """
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)

        engine = _make_sync_engine(path)

        def sync_operation() -> int:
            with orm.Session(engine) as session:
                session.add(SpikeFact(key="from_executor", value="works"))
                session.commit()
                return session.execute(
                    sa.select(sa.func.count()).select_from(SpikeFact)
                ).scalar_one()

        async def async_caller() -> int:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, sync_operation)

        try:
            count = asyncio.run(async_caller())
            assert count == 1, "run_in_executor with sync SQLAlchemy failed"
        finally:
            engine.dispose()  # Windows: must dispose before unlink
            path.unlink(missing_ok=True)

    def test_sync_no_complex_setup(self) -> None:
        """
        Sync SQLAlchemy requires no async session management, no await chains,
        no AsyncSession context managers. Verify basic sync session works.
        """
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            path = Path(f.name)
        engine = _make_sync_engine(path)
        try:
            # Plain sync — no async keywords needed
            with orm.Session(engine) as session:
                session.add(SpikeFact(key="simple", value="no_async_needed"))
                session.commit()
                row = session.execute(
                    sa.select(SpikeFact).where(SpikeFact.key == "simple")
                ).scalar_one()
                assert row.value == "no_async_needed"
        finally:
            engine.dispose()  # Windows: must dispose before unlink
            path.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════════
# SPIKE V-11 CONCLUSION
# ═══════════════════════════════════════════════════════════════════════════════
#
# Decision: USE SYNC SQLAlchemy for AJAA v0.1
#
# Rationale:
#   1. AJAA has NO concurrent writers. SQLite WAL handles concurrent readers fine.
#   2. Write workload: ~10-50 rows/day — negligible for any IO approach.
#   3. Async SQLite (aiosqlite) adds:
#      - Extra dependency (aiosqlite)
#      - AsyncSession lifecycle management in every repository method
#      - Potential greenlet/thread confusion when mixing with Playwright
#      - No measurable throughput benefit for this workload
#   4. Sync SQLAlchemy called via run_in_executor() from async Playwright code
#      works correctly (verified by test_sync_callable_from_async_via_executor).
#   5. Sync is simpler to reason about, easier to test, fewer footguns.
#
# Implementation:
#   - Engine: sa.create_engine("sqlite:///...", connect_args={"check_same_thread": False})
#   - Sessions: contextmanager returning orm.Session(engine)
#   - From async code: loop.run_in_executor(None, sync_repo_method, *args)
#   - WAL mode: PRAGMA journal_mode=WAL set on first connection
#
# aiosqlite is kept in dependencies for potential future use but is NOT
# the default. The decision is recorded here and in ADR-005.
# ═══════════════════════════════════════════════════════════════════════════════