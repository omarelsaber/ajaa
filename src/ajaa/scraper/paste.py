"""
src/ajaa/scraper/paste.py

Manual Job Paste-In source.

Allows the user to paste any job listing directly:
  - apply_url (required)
  - title (optional or extracted)
  - company (optional)
  - location (optional)
  - jd_text (optional)
  - remote_ok (optional)
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from ajaa.scraper.base import RawJob
from ajaa.scraper.normalizer import ingest_job, NormalizeResult, url_hash


@dataclass
class PasteJobInput:
    apply_url: str
    title: str = ""
    company: str = ""
    location: str = ""
    jd_text: str = ""
    remote_ok: bool = True
    salary_raw: str = ""


def ingest_pasted_job(data: PasteJobInput) -> NormalizeResult:
    """Validate and ingest a manually pasted job listing."""
    raw = RawJob(
        source="paste",
        apply_url=data.apply_url.strip(),
        title=data.title.strip() or "Untitled Job",
        company=data.company.strip() or "Unknown Company",
        location=data.location.strip() or ("Remote" if data.remote_ok else ""),
        description=data.jd_text.strip(),
        salary_raw=data.salary_raw.strip(),
        remote=data.remote_ok,
    )
    return ingest_job(raw)