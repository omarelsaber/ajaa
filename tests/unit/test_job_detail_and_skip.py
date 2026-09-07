"""
tests/unit/test_job_detail_and_skip.py

Web route tests for Job Details, Skip, Queue alias, and Application Resolution.
"""
from __future__ import annotations

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from ajaa.db.session import init_engine, reset_engine, get_session
from ajaa.web.app import app
from ajaa.db.repositories import candidate as candidate_repo
from ajaa.db.repositories import fact as fact_repo
from ajaa.types import Confidence, FactSource, FactState
from ajaa.scraper.base import RawJob
from ajaa.scraper.normalizer import ingest_job
from ajaa.db.models import Application, Job
import sqlalchemy as sa


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path, monkeypatch):
    import os
    os.environ["AJAA_TESTING"] = "1"
    monkeypatch.setattr("ajaa.config._settings", None, raising=False)
    monkeypatch.setattr("ajaa.config.Settings.model_config", {"env_prefix": "AJAA_"}, raising=False)
    init_engine(tmp_path / "test_job_detail.db")
    yield
    reset_engine()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def candidate_and_job():
    cand = candidate_repo.create(display_name="Alex Tech")
    cid = cand.id
    fact_repo.upsert(cid, "personal.name.full", "Alex Tech", FactSource.USER_EXPLICIT, Confidence.CONFIRMED, FactState.KNOWN)
    fact_repo.upsert(cid, "skills.primary_language", "Python", FactSource.USER_EXPLICIT, Confidence.CONFIRMED, FactState.KNOWN)
    fact_repo.upsert(cid, "preferences.target_roles", "Senior AI Engineer", FactSource.USER_EXPLICIT, Confidence.CONFIRMED, FactState.KNOWN)

    raw = RawJob(
        source="greenhouse",
        apply_url="https://boards.greenhouse.io/deeptech/jobs/4412",
        title="Senior AI Engineer",
        company="DeepTech AI",
        location="Remote",
        remote=True,
        description="We are seeking a Senior AI Engineer skilled in Python and machine learning.",
    )
    res = ingest_job(raw)
    return cid, res.job_id


class TestJobDetailAndSkip:
    def test_get_job_detail_page(self, client: TestClient, candidate_and_job):
        _, job_id = candidate_and_job
        r = client.get(f"/jobs/{job_id}")
        assert r.status_code == 200
        assert "Senior AI Engineer" in r.text
        assert "DeepTech AI" in r.text
        assert "Match Breakdown" in r.text
        assert "Role Relevance" in r.text
        assert "Queue Application" in r.text

    def test_skip_job_post(self, client: TestClient, candidate_and_job):
        _, job_id = candidate_and_job
        r = client.post(f"/jobs/{job_id}/skip", data={"reason": "Location mismatch"}, follow_redirects=True)
        assert r.status_code == 200
        assert "Skipped" in r.text

        with get_session() as session:
            job = session.execute(sa.select(Job).where(Job.id == job_id)).scalars().first()
            assert job is not None
            assert job.is_stale is True

    def test_queue_job_alias(self, client: TestClient, candidate_and_job):
        _, job_id = candidate_and_job
        r = client.post(f"/jobs/{job_id}/queue", follow_redirects=True)
        assert r.status_code == 200
        assert "Application queued" in r.text

    def test_resolve_and_abandon_application(self, client: TestClient, candidate_and_job):
        cid, job_id = candidate_and_job
        with get_session() as session:
            app_rec = Application(candidate_id=cid, job_id=job_id, state="UNCERTAIN")
            session.add(app_rec)
            session.commit()
            app_id = app_rec.id

        # Resolve to SUBMITTED
        r = client.post(f"/applications/{app_id}/resolve", data={"resolution": "SUBMITTED"}, follow_redirects=True)
        assert r.status_code == 200
        assert "SUBMITTED" in r.text

        # Abandon
        r2 = client.post(f"/applications/{app_id}/abandon", follow_redirects=True)
        assert r2.status_code == 200
        assert "Application discarded" in r2.text
