"""
tests/unit/test_jobs_routes.py

Web route tests for /jobs (list, scrape, paste, apply).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from starlette.testclient import TestClient

from ajaa.db.session import init_engine, reset_engine
from ajaa.web.app import app
from ajaa.scraper.base import RawJob


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path, monkeypatch):
    import os
    os.environ["AJAA_TESTING"] = "1"
    monkeypatch.setattr("ajaa.config._settings", None, raising=False)
    monkeypatch.setattr("ajaa.config.Settings.model_config", {"env_prefix": "AJAA_"}, raising=False)
    init_engine(tmp_path / "test_jobs_routes.db")
    yield
    reset_engine()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


class TestJobsRoutes:
    def test_get_jobs_empty(self, client: TestClient) -> None:
        r = client.get("/jobs")
        assert r.status_code == 200
        assert "Discovered Jobs" in r.text
        assert "No jobs discovered yet" in r.text

    def test_paste_job_route(self, client: TestClient) -> None:
        r = client.post(
            "/jobs/paste",
            data={
                "apply_url": "https://example.com/job/paste-1",
                "title": "Lead Software Engineer",
                "company": "Tech Innovators",
                "location": "Remote",
                "jd_text": "Python, FastAPI, Postgres",
                "remote_ok": "on",
                "salary_raw": "$140,000",
            },
            follow_redirects=True,
        )
        assert r.status_code == 200
        assert "Lead Software Engineer" in r.text
        assert "Tech Innovators" in r.text

    def test_scrape_jobs_route_mocked(self, client: TestClient) -> None:
        mock_raw = [
            RawJob(
                source="remoteok",
                apply_url="https://remoteok.com/job/scraped-1",
                title="Mock Python Dev",
                company="Startup Labs",
                location="Remote",
                description="Python developer wanted",
                remote=True,
            )
        ]
        with patch("ajaa.scraper.remoteok.RemoteOKScraper.scrape", return_value=mock_raw):
            r = client.post(
                "/jobs/scrape",
                data={"keyword": "python"},
                follow_redirects=True,
            )
            assert r.status_code == 200
            assert "Mock Python Dev" in r.text
            assert "Startup Labs" in r.text

    def test_queue_application_route(self, client: TestClient) -> None:
        # First paste a job
        client.post(
            "/jobs/paste",
            data={
                "apply_url": "https://example.com/job/apply-me",
                "title": "Backend Specialist",
                "company": "Fast Corp",
            },
            follow_redirects=True,
        )

        from ajaa.db.session import get_session
        from ajaa.db.models import Job
        import sqlalchemy as sa

        with get_session() as session:
            job = session.execute(sa.select(Job)).scalars().first()
            assert job is not None
            job_id = job.id

        # Queue application
        r = client.post(f"/jobs/{job_id}/apply", follow_redirects=True)
        assert r.status_code == 200
        assert "Application queued" in r.text
        assert "Queued for Apply" in r.text