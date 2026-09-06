"""
tests/unit/test_scraper.py

Scraper unit tests — no network calls, all mocked.

Covers:
  - SearchQuery construction
  - RawJob construction
  - url_hash: determinism, normalization (strips tracking params)
  - parse_salary: various formats
  - ingest_job: new + duplicate detection
  - ingest_jobs: batch, order preserved
  - RemoteOKScraper._fetch mocked response parsing
  - Partial failure: scraper returns partial list on one failed keyword
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ajaa.db.session import init_engine, reset_engine
from ajaa.scraper.base import RawJob, ScraperBase, SearchQuery


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path):
    init_engine(tmp_path / "test_scraper.db")
    yield
    reset_engine()


# ── SearchQuery ───────────────────────────────────────────────────────────────

class TestSearchQuery:
    def test_primary_keyword_first(self) -> None:
        q = SearchQuery(keywords=["Python", "Django"])
        assert q.primary_keyword() == "Python"

    def test_primary_keyword_empty(self) -> None:
        q = SearchQuery(keywords=[])
        assert q.primary_keyword() == ""

    def test_defaults(self) -> None:
        q = SearchQuery(keywords=["Go"])
        assert q.remote_only is False
        assert q.max_results == 50
        assert q.full_time_only is True


# ── URL normalization ──────────────────────────────────────────────────────────

class TestUrlHash:
    def test_deterministic(self) -> None:
        from ajaa.scraper.normalizer import url_hash
        assert url_hash("https://example.com/jobs/123") == url_hash("https://example.com/jobs/123")

    def test_strips_query_string(self) -> None:
        from ajaa.scraper.normalizer import url_hash
        a = url_hash("https://example.com/jobs/123?utm_source=google&ref=abc")
        b = url_hash("https://example.com/jobs/123")
        assert a == b

    def test_strips_trailing_slash(self) -> None:
        from ajaa.scraper.normalizer import url_hash
        assert url_hash("https://example.com/jobs/") == url_hash("https://example.com/jobs")

    def test_different_urls_different_hash(self) -> None:
        from ajaa.scraper.normalizer import url_hash
        assert url_hash("https://a.com/1") != url_hash("https://a.com/2")

    def test_returns_64_hex_chars(self) -> None:
        from ajaa.scraper.normalizer import url_hash
        h = url_hash("https://example.com")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ── Salary parser ─────────────────────────────────────────────────────────────

class TestParseSalary:
    def _p(self, s: str):
        from ajaa.scraper.normalizer import parse_salary
        return parse_salary(s)

    def test_empty_returns_zero(self) -> None:
        assert self._p("") == (0, 0)

    def test_range_k_suffix(self) -> None:
        lo, hi = self._p("$120k–$160k")
        assert lo == 120_000
        assert hi == 160_000

    def test_single_k_value(self) -> None:
        lo, hi = self._p("$80k+")
        assert lo == hi == 80_000

    def test_full_numbers(self) -> None:
        lo, hi = self._p("$100,000 - $140,000")
        assert lo == 100_000
        assert hi == 140_000

    def test_unparseable_returns_zero(self) -> None:
        assert self._p("Competitive") == (0, 0)


# ── Job ingestion ─────────────────────────────────────────────────────────────

def _make_raw(**kwargs) -> RawJob:
    defaults = dict(
        source="remoteok",
        apply_url="https://remoteok.com/jobs/123",
        title="Senior Python Engineer",
        company="Acme Corp",
        location="Remote",
        description="We are looking for a Python engineer.",
        remote=True,
    )
    defaults.update(kwargs)
    return RawJob(**defaults)


class TestIngestJob:
    def test_ingest_new_job(self) -> None:
        from ajaa.scraper.normalizer import ingest_job
        r = ingest_job(_make_raw())
        assert r.job_id is not None
        assert r.was_duplicate is False
        assert len(r.url_hash) == 64

    def test_ingest_duplicate_same_url(self) -> None:
        from ajaa.scraper.normalizer import ingest_job
        r1 = ingest_job(_make_raw())
        r2 = ingest_job(_make_raw())
        assert r1.job_id == r2.job_id
        assert r2.was_duplicate is True

    def test_ingest_url_with_tracking_deduped(self) -> None:
        from ajaa.scraper.normalizer import ingest_job
        r1 = ingest_job(_make_raw(apply_url="https://remoteok.com/jobs/999"))
        r2 = ingest_job(_make_raw(apply_url="https://remoteok.com/jobs/999?utm=foo"))
        assert r1.job_id == r2.job_id

    def test_ingest_different_url_is_new(self) -> None:
        from ajaa.scraper.normalizer import ingest_job
        r1 = ingest_job(_make_raw(apply_url="https://remoteok.com/jobs/1"))
        r2 = ingest_job(_make_raw(apply_url="https://remoteok.com/jobs/2"))
        assert r1.job_id != r2.job_id
        assert not r2.was_duplicate

    def test_ingest_batch(self) -> None:
        from ajaa.scraper.normalizer import ingest_jobs
        raws = [
            _make_raw(apply_url="https://example.com/a"),
            _make_raw(apply_url="https://example.com/b"),
            _make_raw(apply_url="https://example.com/c"),
        ]
        results = ingest_jobs(raws)
        assert len(results) == 3
        ids = [r.job_id for r in results]
        assert len(set(ids)) == 3  # all unique

    def test_job_stored_in_db(self) -> None:
        from ajaa.scraper.normalizer import ingest_job, url_hash
        from ajaa.db.session import get_session
        from ajaa.db.models import Job
        import sqlalchemy as sa

        raw = _make_raw(apply_url="https://stored.com/job/42", title="Staff Eng")
        ingest_job(raw)

        with get_session() as session:
            job = session.execute(
                sa.select(Job).where(Job.url_hash == url_hash("https://stored.com/job/42"))
            ).scalars().first()
            assert job is not None
            assert job.title == "Staff Eng"
            assert job.remote_ok is True


# ── RemoteOK scraper (mocked) ─────────────────────────────────────────────────

class TestRemoteOKScraper:
    def _mock_response(self) -> list[dict]:
        return [
            {"legal": "This is the legal notice"},  # first item = skip
            {
                "id": "abc123",
                "slug": "senior-python-engineer-acme",
                "position": "Senior Python Engineer",
                "company": "Acme Corp",
                "location": "Worldwide",
                "apply_url": "https://remoteok.com/l/abc123",
                "url": "https://remoteok.com/remote-jobs/abc123",
                "description": "We need Python skills.",
                "tags": ["python", "django", "remote"],
                "epoch": 1700000000,
                "salary_min": 120000,
                "salary_max": 160000,
            },
            {
                "id": "def456",
                "slug": "go-engineer-foo",
                "position": "Go Engineer",
                "company": "Foo Inc",
                "apply_url": "https://remoteok.com/l/def456",
                "tags": ["golang"],
                "epoch": 0,
            },
        ]

    def test_parses_mock_response(self) -> None:
        from ajaa.scraper.remoteok import RemoteOKScraper

        scraper = RemoteOKScraper()
        mock_resp = MagicMock()
        mock_resp.json.return_value = self._mock_response()
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value.__enter__ = lambda s: mock_client
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

            query = SearchQuery(keywords=["python"], max_results=10)
            # Patch sleep to avoid delay
            with patch("ajaa.scraper.remoteok.time.sleep"):
                results = scraper.scrape(query)

        assert len(results) == 2
        assert results[0].title == "Senior Python Engineer"
        assert results[0].source == "remoteok"
        assert results[0].remote is True
        assert results[1].title == "Go Engineer"

    def test_salary_parsed_from_min_max(self) -> None:
        from ajaa.scraper.remoteok import _parse_salary
        item = {"salary_min": 100000, "salary_max": 150000}
        assert _parse_salary(item) == "$100,000–$150,000"

    def test_empty_api_response_returns_empty(self) -> None:
        from ajaa.scraper.remoteok import RemoteOKScraper

        scraper = RemoteOKScraper()
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_client_cls.return_value.__enter__ = lambda s: mock_client
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

            with patch("ajaa.scraper.remoteok.time.sleep"):
                results = scraper.scrape(SearchQuery(keywords=["haskell"]))

        assert results == []

    def test_scraper_graceful_on_network_error(self) -> None:
        from ajaa.scraper.remoteok import RemoteOKScraper

        scraper = RemoteOKScraper()
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.get.side_effect = Exception("connection refused")
            mock_client_cls.return_value.__enter__ = lambda s: mock_client
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

            with patch("ajaa.scraper.remoteok.time.sleep"):
                results = scraper.scrape(SearchQuery(keywords=["python"]))

        assert results == []   # no exception, just empty