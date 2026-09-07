"""
src/ajaa/scraper/remoteok.py

RemoteOK scraper.

RemoteOK exposes a JSON API at:
  https://remoteok.com/api?tag=<tag>

Returns an array of job objects (first element is a "legal" notice object).

Rate limit: 1 request per second as per their terms.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

import httpx

from ajaa.scraper.base import RawJob, ScraperBase, SearchQuery

log = logging.getLogger(__name__)

_BASE_URL = "https://remoteok.com/api"
_USER_AGENT = "AJAA/0.1 (github.com/omarelsaber/ajaa; job-application-agent)"
_TIMEOUT = 15.0


class RemoteOKScraper(ScraperBase):
    """
    Scrapes RemoteOK JSON API.

    Converts RemoteOK job tags to search keywords.
    Maps: Python -> python, JavaScript -> javascript, etc.
    """

    SOURCE = "remoteok"
    RATE_LIMIT_DELAY = 1.5

    def scrape(self, query: SearchQuery) -> list[RawJob]:
        results: list[RawJob] = []

        # RemoteOK uses single-word tags (e.g. 'ai', 'engineer', 'python', 'dev')
        tags_to_try: list[str] = []
        for kw in query.keywords:
            clean = kw.lower().strip()
            if not clean:
                continue
            words = [w for w in clean.split() if len(w) > 1]
            for w in words:
                if w not in tags_to_try:
                    tags_to_try.append(w)
            hyphenated = clean.replace(" ", "-")
            if hyphenated not in tags_to_try:
                tags_to_try.append(hyphenated)

        if not tags_to_try:
            tags_to_try = ["ai", "dev", "engineer", "python"]

        for tag in tags_to_try[:4]:  # Max 4 tag calls per query
            try:
                jobs = self._fetch(tag)
                results.extend(jobs)
                if len(results) >= query.max_results:
                    break
                time.sleep(self.RATE_LIMIT_DELAY)
            except Exception as exc:
                log.warning("RemoteOK fetch failed for %r: %s", tag, exc)

        # Dedup by apply_url within this scrape run
        seen: set[str] = set()
        unique: list[RawJob] = []
        for job in results:
            if job.apply_url not in seen:
                seen.add(job.apply_url)
                unique.append(job)

        return unique[: query.max_results]

    def _fetch(self, tag: str) -> list[RawJob]:
        url = f"{_BASE_URL}?tag={tag}"
        log.debug("RemoteOK GET %s", url)

        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(url, headers={"User-Agent": _USER_AGENT})
            resp.raise_for_status()
            data = resp.json()

        # First element is legal notice, skip it
        if not isinstance(data, list) or len(data) < 2:
            return []

        raw_jobs: list[RawJob] = []
        for item in data[1:]:
            if not isinstance(item, dict):
                continue
            apply_url = item.get("apply_url") or item.get("url", "")
            if not apply_url:
                continue

            # Parse posted_at (epoch int)
            epoch = item.get("epoch", 0)
            posted_at = ""
            if epoch:
                try:
                    posted_at = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
                except Exception:
                    pass

            raw_jobs.append(RawJob(
                source=self.SOURCE,
                apply_url=apply_url,
                title=item.get("position", ""),
                company=item.get("company", ""),
                location=item.get("location", "Worldwide"),
                description=item.get("description", ""),
                salary_raw=_parse_salary(item),
                posted_at=posted_at,
                tags=item.get("tags", []) or [],
                remote=True,  # RemoteOK is always remote
                extra={"slug": item.get("slug", ""), "id": item.get("id", "")},
            ))

        return raw_jobs


def _parse_salary(item: dict) -> str:
    lo = item.get("salary_min", 0) or 0
    hi = item.get("salary_max", 0) or 0
    if lo and hi:
        return f"${lo:,}–${hi:,}"
    if lo:
        return f"${lo:,}+"
    return ""