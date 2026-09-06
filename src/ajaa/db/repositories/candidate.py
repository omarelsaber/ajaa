"""
src/ajaa/db/repositories/candidate.py

CandidateContext repository.

Responsibility: ONE row per installation.
- get() returns the single candidate or raises NoCandidateError
- create() creates the row; raises if already exists
- update() updates mutable fields only
"""
from __future__ import annotations

from ajaa.db.models import CandidateContext
from ajaa.db.session import get_session


class NoCandidateError(Exception):
    """Raised when no candidate_context row exists (ajaa init not run)."""


class CandidateAlreadyExistsError(Exception):
    """Raised when create() is called but a row already exists."""


def get() -> CandidateContext:
    """
    Return the single CandidateContext row.
    Raises NoCandidateError if not initialized.
    """
    import sqlalchemy as sa

    with get_session() as session:
        rows = session.execute(sa.select(CandidateContext)).scalars().all()
        if not rows:
            raise NoCandidateError(
                "No candidate profile found.\n"
                "Run 'ajaa init' to set up your profile."
            )
        # Defensive: return last created if somehow multiple exist
        row = sorted(rows, key=lambda r: r.created_at)[0]
        session.expunge(row)
        return row


def get_or_none() -> CandidateContext | None:
    """Return the candidate or None if not initialized."""
    try:
        return get()
    except NoCandidateError:
        return None


def create(display_name: str, locale: str = "en-US") -> CandidateContext:
    """
    Create the candidate profile row. Refuses if one already exists.
    """
    import sqlalchemy as sa

    with get_session() as session:
        existing = session.execute(sa.select(CandidateContext)).scalars().first()
        if existing is not None:
            raise CandidateAlreadyExistsError(
                f"A candidate profile already exists (id={existing.id}). "
                "AJAA is single-installation. Run 'ajaa doctor' to inspect."
            )
        ctx = CandidateContext(display_name=display_name, locale=locale)
        session.add(ctx)
        session.commit()
        session.expunge(ctx)
        return ctx


def update(
    *,
    display_name: str | None = None,
    locale: str | None = None,
    calibration_completed: bool | None = None,
) -> CandidateContext:
    """Update mutable fields on the candidate. Returns updated row."""
    import sqlalchemy as sa

    with get_session() as session:
        row = session.execute(sa.select(CandidateContext)).scalars().first()
        if row is None:
            raise NoCandidateError("No candidate profile. Run 'ajaa init'.")
        if display_name is not None:
            row.display_name = display_name
        if locale is not None:
            row.locale = locale
        if calibration_completed is not None:
            row.calibration_completed = calibration_completed
        session.commit()
        session.expunge(row)
        return row