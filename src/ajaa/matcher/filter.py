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
    exclude_applied: bool = True,
    candidate_credentials: list[str] | None = None,
) -> FilterResult:
    """
    Apply hard pre-filters to a job dict.

    job: dict with keys matching Job model columns
    candidate_id: used to check existing applications
    company_blacklist: optional list of company name substrings to reject
    exclude_applied: if True, filter out jobs already applied to

    Returns FilterResult(passed=True) if job should proceed to scoring.
    """
    # ── Quarantine gate (PRD §23.6 / §33.6) ──────────────────────────────────
    if job.get("quarantined", False) or job.get("injection_suspected", False):
        reason = job.get("quarantine_reason") or "job quarantined for suspected prompt injection"
        return FilterResult(passed=False, reason=f"quarantined: {reason}")

    # ── Credential gate (PRD §11.7, §33.9: No soft credit) ───────────────────
    required_creds = job.get("required_credentials") or []
    if required_creds:
        c_creds = {str(c).strip().upper() for c in (candidate_credentials or [])}
        for req in required_creds:
            if req.strip().upper() not in c_creds:
                return FilterResult(
                    passed=False,
                    reason=f"credential_missing: requirement '{req}' not held by candidate",
                )

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
    if exclude_applied and job_id and candidate_id:
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