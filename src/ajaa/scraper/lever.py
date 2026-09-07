"""
src/ajaa/scraper/lever.py

Lever ATS Job Board Scraper.

Uses Lever public postings API:
  GET https://api.lever.co/v0/postings/{site}?mode=json

No authentication required.
"""
from __future__ import annotations

import logging
import httpx

from ajaa.scraper.base import RawJob, ScraperBase, SearchQuery

log = logging.getLogger(__name__)

_BASE_URL = "https://api.lever.co/v0/postings"
_TIMEOUT = 15.0


class LeverScraper(ScraperBase):
    SOURCE = "lever"
    RATE_LIMIT_DELAY = 1.0

    def __init__(self, sites: list[str] | None = None):
        self.sites = sites or [
            "spotify",
            "palantir",
        ]

    def scrape(self, query: SearchQuery) -> list[RawJob]:
        all_jobs: list[RawJob] = []

        sites_to_scrape = self.sites
        explicit_sites = [
            k.split(":", 1)[1].strip()
            for k in query.keywords
            if k.lower().startswith("lever:")
        ]
        if explicit_sites:
            sites_to_scrape = explicit_sites

        for site in sites_to_scrape[:5]:
            try:
                jobs = self.scrape_site(site, query)
                all_jobs.extend(jobs)
                if len(all_jobs) >= query.max_results:
                    break
            except Exception as exc:
                log.warning("Lever fetch failed for site %r: %s", site, exc)

        return all_jobs[: query.max_results]

    def scrape_site(self, site: str, query: SearchQuery | None = None) -> list[RawJob]:
        url = f"{_BASE_URL}/{site}?mode=json"
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            items = resp.json()

        if not isinstance(items, list):
            return []

        raw_jobs: list[RawJob] = []
        keywords = [k.lower().strip() for k in (query.keywords if query else []) if not k.startswith("lever:")]

        for item in items:
            title = item.get("text", "")
            apply_url = item.get("applyUrl") or item.get("hostedUrl", "")
            if not apply_url:
                continue

            if keywords:
                title_lower = title.lower()
                if not any(kw in title_lower for kw in keywords):
                    continue

            cats = item.get("categories", {}) or {}
            location = cats.get("location", "") or "Remote"
            commitment = cats.get("commitment", "")
            desc = item.get("descriptionPlain") or item.get("description", "")
            created_at = item.get("createdAt", 0)

            posted_at = ""
            if created_at:
                from datetime import datetime, timezone
                try:
                    posted_at = datetime.fromtimestamp(created_at / 1000.0, tz=timezone.utc).isoformat()
                except Exception:
                    pass

            is_remote = "remote" in location.lower() or "remote" in title.lower() or cats.get("workplaceType", "").lower() == "remote"
            if query and query.remote_only and not is_remote:
                continue

            raw_jobs.append(RawJob(
                source=f"lever:{site}",
                apply_url=apply_url,
                title=title,
                company=site.capitalize(),
                location=location,
                description=desc,
                posted_at=posted_at,
                remote=is_remote,
                extra={"lever_id": item.get("id"), "site": site, "commitment": commitment},
            ))

        return raw_jobs