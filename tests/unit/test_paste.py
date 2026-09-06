"""
tests/unit/test_paste.py

Unit tests for manual job paste-in source.
"""
from __future__ import annotations

from pathlib import Path
import pytest

from ajaa.db.session import init_engine, reset_engine
from ajaa.scraper.paste import PasteJobInput, ingest_pasted_job


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path):
    init_engine(tmp_path / "test_paste.db")
    yield
    reset_engine()


class TestPasteJob:
    def test_ingest_pasted_job(self) -> None:
        inp = PasteJobInput(
            apply_url="https://jobs.example.com/senior-dev",
            title="Senior Python Architect",
            company="Globex Corporation",
            location="Remote",
            jd_text="Looking for an architect with Python and AWS experience.",
            remote_ok=True,
            salary_raw="$150,000 - $180,000",
        )
        res = ingest_pasted_job(inp)
        assert res.job_id is not None
        assert not res.was_duplicate
        assert len(res.url_hash) == 64

    def test_ingest_duplicate_detected(self) -> None:
        inp = PasteJobInput(
            apply_url="https://jobs.example.com/duplicate-test",
            title="Dev",
        )
        r1 = ingest_pasted_job(inp)
        r2 = ingest_pasted_job(inp)
        assert r1.job_id == r2.job_id
        assert r2.was_duplicate is True

    def test_default_values_when_empty(self) -> None:
        inp = PasteJobInput(
            apply_url="https://jobs.example.com/minimal",
        )
        res = ingest_pasted_job(inp)
        assert res.job_id is not None
        assert not res.was_duplicate