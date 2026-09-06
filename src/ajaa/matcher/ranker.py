"""
src/ajaa/matcher/ranker.py

Takes a list of (job_dict, MatchScore) and produces a ranked list.

Ranking logic:
  1. Disqualified jobs -> excluded
  2. Sort by score DESC
  3. Secondary sort: recent jobs first (discovered_at DESC)
  4. Pagination support

Also contains the full pipeline: load jobs -> filter -> score -> rank
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ajaa.matcher.scorer import MatchScore, score_job
from ajaa.matcher.filter import FilterResult, apply_hard_filters


@dataclass
class RankedJob:
    job_id: str
    job: dict[str, Any]
    score: MatchScore
    rank: int


def rank_jobs(
    profile: dict,
    jobs: list[dict],
    candidate_id: str = "",
    company_blacklist: list[str] | None = None,
    threshold: int = 50,
    page: int = 1,
    page_size: int = 25,
) -> list[RankedJob]:
    """
    Filter, score, and rank a list of job dicts.

    profile: CanonicalProfile.to_dict()
    jobs: list of dicts from Job model
    threshold: minimum score to include in results (default 50)

    Returns paginated list of RankedJob, ordered by score DESC.
    """
    scored: list[tuple[dict, MatchScore]] = []

    for job in jobs:
        # Hard filter first (cheap)
        f: FilterResult = apply_hard_filters(job, candidate_id, company_blacklist)
        if not f.passed:
            continue

        # Score
        s: MatchScore = score_job(profile, job)
        if not s.is_qualified(threshold):
            continue

        scored.append((job, s))

    # Sort: score DESC, then discovered_at DESC (newer first)
    def sort_key(item: tuple[dict, MatchScore]):
        job, s = item
        ts = job.get("discovered_at")
        if isinstance(ts, datetime):
            epoch = ts.timestamp()
        elif isinstance(ts, str):
            try:
                epoch = datetime.fromisoformat(ts).timestamp()
            except Exception:
                epoch = 0.0
        else:
            epoch = 0.0
        return (s.total, epoch)

    scored.sort(key=sort_key, reverse=True)

    # Paginate
    start = (page - 1) * page_size
    end = start + page_size
    page_items = scored[start:end]

    return [
        RankedJob(
            job_id=job.get("id", ""),
            job=job,
            score=s,
            rank=start + i + 1,
        )
        for i, (job, s) in enumerate(page_items)
    ]


def load_and_rank(
    profile: dict,
    candidate_id: str,
    company_blacklist: list[str] | None = None,
    threshold: int = 50,
    page: int = 1,
    page_size: int = 25,
    source: str | None = None,
) -> list[RankedJob]:
    """
    Full pipeline: load jobs from DB -> filter -> score -> rank.

    source: optional filter by source_connector (e.g. "remoteok")
    """
    from ajaa.db.session import get_session
    from ajaa.db.models import Job
    import sqlalchemy as sa

    with get_session() as session:
        q = sa.select(Job).where(Job.is_stale == False)
        if source:
            q = q.where(Job.source_connector == source)
        q = q.order_by(Job.discovered_at.desc()).limit(500)
        rows = session.execute(q).scalars().all()
        jobs = [
            {
                "id": r.id,
                "title": r.title,
                "company": r.company,
                "location": r.location,
                "remote_ok": r.remote_ok,
                "jd_text": r.jd_text,
                "tags_json": "",          # not in model yet — future
                "salary_min": None,
                "salary_max": None,
                "is_stale": r.is_stale,
                "discovered_at": r.discovered_at,
                "source": r.source_connector,
                "apply_url": r.apply_url,
            }
            for r in rows
        ]

    return rank_jobs(
        profile=profile,
        jobs=jobs,
        candidate_id=candidate_id,
        company_blacklist=company_blacklist,
        threshold=threshold,
        page=page,
        page_size=page_size,
    )