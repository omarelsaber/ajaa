"""
src/ajaa/matcher/filter.py

Hard pre-filters applied before scoring.

A job that fails a hard filter is never scored or applied to.
Filters are cheap boolean checks — no LLM.

Hard filter rules:
  - is_stale=True         -> discard (job URL no longer responds 200)
  - blacklisted company   -> discard
  - already applied       -> skip (not discard — track in applications)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FilterResult:
    passed: bool
    reason: str = ""          # populated when passed=False


def apply_hard_filters(
    job: dict,
    candidate_id: str,
    company_blacklist: list[str] | None = None,
) -> FilterResult:
    """
    Apply hard pre-filters to a job dict.

    job: dict with keys matching Job model columns
    candidate_id: used to check existing applications
    company_blacklist: optional list of company name substrings to reject

    Returns FilterResult(passed=True) if job should proceed to scoring.
    """
    # ── Staleness gate ────────────────────────────────────────────────────────
    if job.get("is_stale", False):
        return FilterResult(passed=False, reason="job is stale (URL dead)")

    # ── Company blacklist ─────────────────────────────────────────────────────
    company = (job.get("company", "") or "").lower()
    for blocked in (company_blacklist or []):
        if blocked.lower() in company:
            return FilterResult(passed=False, reason=f"company '{company}' is blacklisted")

    # ── Already applied ───────────────────────────────────────────────────────
    job_id = job.get("id")
    if job_id and candidate_id:
        already = _has_application(candidate_id, job_id)
        if already:
            return FilterResult(passed=False, reason="already applied")

    return FilterResult(passed=True)


def _has_application(candidate_id: str, job_id: str) -> bool:
    """Check if candidate already has an application for this job."""
    try:
        from ajaa.db.session import get_session
        from ajaa.db.models import Application
        import sqlalchemy as sa

        with get_session() as session:
            count = session.execute(
                sa.select(sa.func.count()).select_from(Application).where(
                    Application.candidate_id == candidate_id,
                    Application.job_id == job_id,
                )
            ).scalar_one()
            return count > 0
    except Exception:
        return False