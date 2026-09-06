"""
src/ajaa/scraper/base.py

Abstract scraper interface + shared utilities.

Every scraper:
  1. Accepts a SearchQuery (keywords, location, remote, etc.)
  2. Returns a list of RawJob dicts (unvalidated)
  3. Never writes to DB — that is the normalizer's job

Scrapers must be:
  - Stateless (no instance state between calls)
  - Respectful (rate-limit headers, user-agent, robots.txt)
  - Resilient (return partial results on error, log failures)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SearchQuery:
    """Structured job search query."""
    keywords: list[str]          # e.g. ["Python", "Backend Engineer"]
    location: str = ""           # e.g. "Remote", "New York, NY"
    remote_only: bool = False
    full_time_only: bool = True
    max_results: int = 50        # Upper bound per scraper call
    min_salary_usd: int = 0      # 0 = no filter
    experience_levels: list[str] = field(default_factory=list)  # e.g. ["mid", "senior"]

    def primary_keyword(self) -> str:
        return self.keywords[0] if self.keywords else ""


@dataclass
class RawJob:
    """
    Raw, unvalidated job data from a scraper.
    All fields optional — normalizer validates and fills gaps.
    """
    source: str               # e.g. "remoteok", "linkedin"
    apply_url: str            # Canonical URL (dedup key)
    title: str = ""
    company: str = ""
    location: str = ""
    description: str = ""
    salary_raw: str = ""      # e.g. "$120k-$160k", unparsed
    posted_at: str = ""       # ISO string or human-readable
    tags: list[str] = field(default_factory=list)
    remote: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class ScraperBase(ABC):
    """Abstract base for all job scrapers."""

    SOURCE: str = ""          # Override in subclass, e.g. "remoteok"
    RATE_LIMIT_DELAY: float = 1.0  # Seconds between requests

    @abstractmethod
    def scrape(self, query: SearchQuery) -> list[RawJob]:
        """
        Execute a search and return raw job results.

        Must not raise — catch exceptions internally and return partial results.
        Must honour query.max_results.
        """

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} source={self.SOURCE!r}>"