"""
src/ajaa/scraper/normalizer.py

Job normalizer: RawJob -> Job DB row.

Responsibilities:
  1. Compute url_hash = SHA-256(normalize(apply_url))
  2. Check if job already in DB (dedup by url_hash)
  3. Parse salary_raw into salary_min/max integers
  4. Insert new job or return existing ID
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse

from ajaa.scraper.base import RawJob

log = logging.getLogger(__name__)


@dataclass
class NormalizeResult:
    job_id: str
    was_duplicate: bool
    url_hash: str


def normalize_url(url: str) -> str:
    """Normalize apply URL for stable hashing (strip tracking params)."""
    try:
        parsed = urlparse(url.strip())
        cleaned = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
        return cleaned.rstrip("/")
    except Exception:
        return url.strip()


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()


def parse_salary(raw: str) -> tuple[int, int]:
    """
    Parse salary string into (min, max) annual USD integers.
    Returns (0, 0) if unparseable.
    Handles: "$120k-$160k", "$100,000 - $140,000", "$80k+"
    """
    if not raw:
        return (0, 0)
    clean = raw.lower().replace(",", "").replace(" ", "")
    # Find all number+optional-suffix patterns
    parts = re.findall(r"(\d+(?:\.\d+)?)([km]?)", clean)
    parsed: list[int] = []
    for num_str, suffix in parts:
        val = float(num_str)
        if suffix == "k":
            val *= 1_000
        elif suffix == "m":
            val *= 1_000_000
        if val < 500:          # looks like hourly rate
            val *= 2_000
        parsed.append(int(val))
    if not parsed:
        return (0, 0)
    if len(parsed) == 1:
        return (parsed[0], parsed[0])
    return (min(parsed), max(parsed))


def ingest_job(raw: RawJob) -> NormalizeResult:
    """
    Normalize and persist a RawJob to the jobs table.
    Returns NormalizeResult with was_duplicate=True if url_hash already exists.
    """
    from ajaa.db.session import get_session
    from ajaa.db.models import Job
    import sqlalchemy as sa

    uhash = url_hash(raw.apply_url)

    with get_session() as session:
        existing = session.execute(
            sa.select(Job).where(Job.url_hash == uhash)
        ).scalars().first()

        if existing is not None:
            # Update last_seen
            session.execute(
                sa.update(Job).where(Job.id == existing.id).values(
                    jd_scraped_at=datetime.now(timezone.utc)
                )
            )
            session.commit()
            return NormalizeResult(
                job_id=existing.id,
                was_duplicate=True,
                url_hash=uhash,
            )

        now = datetime.now(timezone.utc)

        # Parse posted_at for jd_scraped_at
        jd_scraped_at = None
        if raw.posted_at:
            try:
                jd_scraped_at = datetime.fromisoformat(
                    raw.posted_at.replace("Z", "+00:00")
                )
            except Exception:
                pass

        job = Job(
            url_hash=uhash,
            apply_url=raw.apply_url,
            source_connector=raw.source,
            title=raw.title[:500] if raw.title else "",
            company=raw.company[:200] if raw.company else "",
            location=raw.location[:200] if raw.location else "",
            remote_ok=raw.remote,
            jd_text=raw.description[:50_000] if raw.description else None,
            jd_content_hash=hashlib.sha256(
                (raw.description or "").encode()
            ).hexdigest() if raw.description else None,
            jd_scraped_at=jd_scraped_at or now,
            discovered_at=now,
            is_stale=False,
        )
        session.add(job)
        session.flush()
        job_id = job.id
        session.commit()

    return NormalizeResult(job_id=job_id, was_duplicate=False, url_hash=uhash)


def ingest_jobs(raws: list[RawJob]) -> list[NormalizeResult]:
    """Batch ingest, returns results in same order."""
    return [ingest_job(r) for r in raws]