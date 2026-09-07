"""
src/ajaa/scraper/ashby.py

Ashby ATS Job Board Scraper (PRD §10.2, §17.2, §18.3).

Uses Ashby's public postings API:
  GET https://api.ashbyhq.com/posting-api/job-board/{board_name}?includeCompensation=true

No authentication required.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
import httpx

from ajaa.scraper.base import RawJob, ScraperBase, SearchQuery

log = logging.getLogger(__name__)

_BASE_URL = "https://api.ashbyhq.com/posting-api/job-board"
_TIMEOUT = 15.0


class AshbyScraper(ScraperBase):
    SOURCE = "ashby"
    RATE_LIMIT_DELAY = 1.0

    def __init__(self, boards: list[str] | None = None):
        self.boards = boards or [
            "openai",
            "linear",
            "retool",
            "ramp",
            "perplexity",
            "notion",
        ]

    def scrape(self, query: SearchQuery) -> list[RawJob]:
        all_jobs: list[RawJob] = []

        boards_to_scrape = self.boards
        explicit_boards = [
            k.split(":", 1)[1].strip()
            for k in query.keywords
            if k.lower().startswith("ashby:")
        ]
        if explicit_boards:
            boards_to_scrape = explicit_boards

        for board in boards_to_scrape[:6]:
            try:
                jobs = self.scrape_board(board, query)
                all_jobs.extend(jobs)
                if len(all_jobs) >= query.max_results:
                    break
            except Exception as exc:
                log.warning("Ashby fetch failed for board %r: %s", board, exc)

        return all_jobs[: query.max_results]

    def scrape_board(self, board: str, query: SearchQuery | None = None) -> list[RawJob]:
        url = f"{_BASE_URL}/{board}?includeCompensation=true"
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        jobs_list = data.get("jobs", []) if isinstance(data, dict) else []
        if not isinstance(jobs_list, list):
            return []

        raw_jobs: list[RawJob] = []
        keywords = [
            k.lower().strip()
            for k in (query.keywords if query else [])
            if not k.startswith("ashby:")
        ]

        for item in jobs_list:
            title = item.get("title", "")
            job_id = str(item.get("id", ""))
            apply_url = item.get("applyUrl") or item.get("jobUrl") or f"https://jobs.ashbyhq.com/{board}/{job_id}"
            if not apply_url:
                continue

            if keywords:
                title_lower = title.lower()
                department = str(item.get("department", "")).lower()
                team = str(item.get("team", "")).lower()
                combined = f"{title_lower} {department} {team}"
                if not any(kw in combined for kw in keywords):
                    continue

            location = str(item.get("locationName") or item.get("location") or "Remote")
            is_remote = bool(item.get("isRemote")) or "remote" in location.lower() or "remote" in title.lower()
            if query and query.remote_only and not is_remote:
                continue

            desc = item.get("descriptionPlain") or item.get("descriptionHtml") or ""
            published_at = item.get("publishedAt", "")
            posted_at = ""
            if published_at:
                try:
                    posted_at = datetime.fromisoformat(published_at.replace("Z", "+00:00")).isoformat()
                except Exception:
                    posted_at = str(published_at)

            # Compensation parsing
            salary_raw = ""
            comp = item.get("compensation")
            if isinstance(comp, dict):
                comp_summary = comp.get("compensationTierSummary")
                if comp_summary:
                    salary_raw = str(comp_summary)
                else:
                    min_val = comp.get("minValue")
                    max_val = comp.get("maxValue")
                    curr = comp.get("currencyCode", "USD")
                    if min_val and max_val:
                        salary_raw = f"{curr} {min_val:,} - {max_val:,}"
                    elif min_val:
                        salary_raw = f"{curr} {min_val:,}+"

            tags = []
            if item.get("department"):
                tags.append(str(item.get("department")))
            if item.get("team"):
                tags.append(str(item.get("team")))
            if item.get("employmentType"):
                tags.append(str(item.get("employmentType")))

            raw_jobs.append(
                RawJob(
                    source=f"ashby:{board}",
                    apply_url=apply_url,
                    title=title,
                    company=board.capitalize(),
                    location=location,
                    description=desc,
                    salary_raw=salary_raw,
                    posted_at=posted_at,
                    tags=tags,
                    remote=is_remote,
                    extra={
                        "ashby_id": job_id,
                        "department": item.get("department"),
                        "team": item.get("team"),
                        "employment_type": item.get("employmentType"),
                    },
                )
            )

        return raw_jobs
