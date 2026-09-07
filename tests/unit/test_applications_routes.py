"""
tests/unit/test_applications_routes.py

Web route tests for /applications.
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
from ajaa.db.models import Application


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path, monkeypatch):
    import os
    os.environ["AJAA_TESTING"] = "1"
    monkeypatch.setattr("ajaa.config._settings", None, raising=False)
    monkeypatch.setattr("ajaa.config.Settings.model_config", {"env_prefix": "AJAA_"}, raising=False)
    init_engine(tmp_path / "test_apps_routes.db")
    yield
    reset_engine()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def candidate_and_job():
    cand = candidate_repo.create(display_name="AppTester")
    cid = cand.id
    fact_repo.upsert(cid, "personal.name.full", "App Tester", FactSource.USER_EXPLICIT, Confidence.CONFIRMED, FactState.KNOWN)
    fact_repo.upsert(cid, "personal.email.primary", "app@test.com", FactSource.USER_EXPLICIT, Confidence.CONFIRMED, FactState.KNOWN)
    fact_repo.upsert(cid, "personal.phone.primary", "+1-555-4321", FactSource.USER_EXPLICIT, Confidence.CONFIRMED, FactState.KNOWN)
    fact_repo.upsert(cid, "work_authorization.requires_sponsorship", "No", FactSource.USER_EXPLICIT, Confidence.CONFIRMED, FactState.KNOWN)

    raw = RawJob(source="manual", apply_url="https://jobs.example.com/eng", title="Frontend Engineer", company="Acme Inc")
    job_res = ingest_job(raw)

    with get_session() as session:
        application = Application(
            candidate_id=cid,
            job_id=job_res.job_id,
            state="QUEUED",
        )
        session.add(application)
        session.commit()
        app_id = application.id

    return cid, job_res.job_id, app_id


class TestApplicationsRoutes:
    def test_get_applications_list(self, client: TestClient, candidate_and_job):
        _, _, app_id = candidate_and_job
        r = client.get("/applications")
        assert r.status_code == 200
        assert "Applications Tracker" in r.text
        assert "Frontend Engineer" in r.text
        assert "QUEUED" in r.text

    def test_prepare_application_route(self, client: TestClient, candidate_and_job):
        _, _, app_id = candidate_and_job
        r = client.post(f"/applications/{app_id}/prepare", follow_redirects=True)
        assert r.status_code == 200
        assert "READY_FOR_REVIEW" in r.text
        assert "Approve" in r.text

    def test_approve_application_route(self, client: TestClient, candidate_and_job):
        _, _, app_id = candidate_and_job
        client.post(f"/applications/{app_id}/prepare", follow_redirects=True)
        r = client.post(f"/applications/{app_id}/approve", follow_redirects=True)
        assert r.status_code == 200
        assert "APPROVED" in r.text
        assert "Submit Application" in r.text

    def test_submit_application_route(self, client: TestClient, candidate_and_job):
        _, _, app_id = candidate_and_job
        client.post(f"/applications/{app_id}/prepare", follow_redirects=True)
        client.post(f"/applications/{app_id}/approve", follow_redirects=True)
        r = client.post(f"/applications/{app_id}/submit", follow_redirects=True)
        assert r.status_code == 200
        assert "SUBMITTED" in r.text

    def test_reject_application_route(self, client: TestClient, candidate_and_job):
        _, _, app_id = candidate_and_job
        r = client.post(f"/applications/{app_id}/reject", follow_redirects=True)
        assert r.status_code == 200
        assert "REJECTED" in r.text

    def test_get_application_replay_detail(self, client: TestClient, candidate_and_job):
        """PRD §31.2: Replay detail page displays full provenance, steps, and Q&A."""
        _, _, app_id = candidate_and_job
        client.post(f"/applications/{app_id}/prepare", follow_redirects=True)
        r = client.get(f"/applications/{app_id}")
        assert r.status_code == 200
        assert "Replay" in r.text
        assert "Frontend Engineer" in r.text
        assert "Test Dry-Run (Safe)" in r.text
        assert "Grounded Questions" in r.text
        assert "Immutable Audit Chain Log" in r.text

    def test_approve_all_route(self, client: TestClient, candidate_and_job):
        """Bulk approval for READY_FOR_REVIEW applications."""
        _, _, app_id = candidate_and_job
        client.post(f"/applications/{app_id}/prepare", follow_redirects=True)
        r = client.post("/applications/approve-all", follow_redirects=True)
        assert r.status_code == 200
        assert "Approved 1 applications" in r.text
        assert "APPROVED" in r.text