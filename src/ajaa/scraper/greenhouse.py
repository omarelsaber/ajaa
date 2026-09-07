"""
src/ajaa/scraper/greenhouse.py

Greenhouse ATS Job Board Scraper.

Uses Greenhouse publicly accessible Board API:
  GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true

No authentication required.
"""
from __future__ import annotations

import logging
from typing import Any
import httpx

from ajaa.scraper.base import RawJob, ScraperBase, SearchQuery

log = logging.getLogger(__name__)

_BASE_URL = "https://boards-api.greenhouse.io/v1/boards"
_TIMEOUT = 15.0


class GreenhouseScraper(ScraperBase):
    SOURCE = "greenhouse"
    RATE_LIMIT_DELAY = 1.0

    def __init__(self, board_tokens: list[str] | None = None):
        self.board_tokens = board_tokens or [
            "cloudflare",
            "elastic",
            "automattic",
            "canonical",
            "figma",
            "stripe",
            "reddit",
            "datadog",
        ]

    def scrape(self, query: SearchQuery) -> list[RawJob]:
        all_jobs: list[RawJob] = []

        # If keywords specified board tokens (e.g. board:cloudflare)
        tokens_to_scrape = self.board_tokens
        explicit_tokens = [
            k.split(":", 1)[1].strip()
            for k in query.keywords
            if k.lower().startswith("board:")
        ]
        if explicit_tokens:
            tokens_to_scrape = explicit_tokens

        for token in tokens_to_scrape[:5]:  # Safety ceiling: max 5 boards per scrape run
            try:
                jobs = self.scrape_board(token, query)
                all_jobs.extend(jobs)
                if len(all_jobs) >= query.max_results:
                    break
            except Exception as exc:
                log.warning("Greenhouse board fetch failed for token %r: %s", token, exc)

        return all_jobs[: query.max_results]

    def scrape_board(self, board_token: str, query: SearchQuery | None = None) -> list[RawJob]:
        url = f"{_BASE_URL}/{board_token}/jobs?content=true"
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        jobs_list = data.get("jobs", [])
        raw_jobs: list[RawJob] = []

        keywords = [k.lower().strip() for k in (query.keywords if query else []) if not k.startswith("board:")]

        for item in jobs_list:
            title = item.get("title", "")
            apply_url = item.get("absolute_url", "")
            if not apply_url:
                continue

            # Filter by keywords if provided
            if keywords:
                title_lower = title.lower()
                if not any(kw in title_lower for kw in keywords):
                    continue

            location_name = ""
            loc = item.get("location")
            if isinstance(loc, dict):
                location_name = loc.get("name", "")

            content = item.get("content", "")
            updated_at = item.get("updated_at", "")

            # Detect remote
            is_remote = "remote" in location_name.lower() or "remote" in title.lower()
            if query and query.remote_only and not is_remote:
                continue

            raw_jobs.append(RawJob(
                source=f"greenhouse:{board_token}",
                apply_url=apply_url,
                title=title,
                company=board_token.capitalize(),
                location=location_name or "Remote",
                description=content,
                posted_at=updated_at,
                remote=is_remote,
                extra={"greenhouse_id": item.get("id"), "board_token": board_token},
            ))

        return raw_jobs