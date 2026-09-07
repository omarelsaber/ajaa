"""
tests/unit/test_profile_routes.py

Web route tests for Candidate Profile & Fact Ledger (/profile).
"""
from __future__ import annotations

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from ajaa.db.session import init_engine, reset_engine
from ajaa.web.app import app
from ajaa.db.repositories import candidate as candidate_repo
from ajaa.db.repositories import fact as fact_repo
from ajaa.types import Confidence, FactSource, FactState


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path, monkeypatch):
    import os
    os.environ["AJAA_TESTING"] = "1"
    monkeypatch.setattr("ajaa.config._settings", None, raising=False)
    monkeypatch.setattr("ajaa.config.Settings.model_config", {"env_prefix": "AJAA_"}, raising=False)
    init_engine(tmp_path / "test_profile_routes.db")
    yield
    reset_engine()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def candidate_with_facts():
    cand = candidate_repo.create(display_name="Jordan Doe")
    cid = cand.id
    fact_repo.upsert(cid, "personal.name.full", "Jordan Doe", FactSource.USER_EXPLICIT, Confidence.CONFIRMED, FactState.KNOWN)
    fact_repo.upsert(cid, "personal.email.primary", "jordan@example.com", FactSource.USER_EXPLICIT, Confidence.CONFIRMED, FactState.KNOWN)
    fact_repo.upsert(cid, "skills.primary_language", "Python", FactSource.CV_EXPLICIT, Confidence.HIGH, FactState.KNOWN)
    fact_repo.upsert(cid, "preferences.work_mode", "remote", FactSource.USER_CONFIRMED_SUGGESTION, Confidence.CONFIRMED, FactState.KNOWN)
    return cand


class TestProfileRoutes:
    def test_get_profile_view(self, client: TestClient, candidate_with_facts):
        r = client.get("/profile")
        assert r.status_code == 200
        assert "Candidate Fact Ledger" in r.text
        assert "Jordan Doe" in r.text
        assert "jordan@example.com" in r.text
        assert "Python" in r.text
        assert "Core Knowledge Coverage" in r.text
        assert "Profile Version Hash" in r.text

    def test_add_fact_post(self, client: TestClient, candidate_with_facts):
        r = client.post(
            "/profile/facts",
            data={
                "fact_key": "skills.frameworks",
                "fact_value": "FastAPI, PyTorch",
                "confidence": "HIGH",
            },
            follow_redirects=True,
        )
        assert r.status_code == 200
        assert "skills.frameworks" in r.text
        assert "FastAPI, PyTorch" in r.text

        # Verify it has Rank 1 (USER_EXPLICIT)
        fact = fact_repo.get_canonical(candidate_with_facts.id, "skills.frameworks")
        assert fact is not None
        assert fact.source_rank == FactSource.USER_EXPLICIT.rank
        assert fact.fact_value == "FastAPI, PyTorch"

    def test_delete_fact_post(self, client: TestClient, candidate_with_facts):
        r = client.post(
            "/profile/facts/delete",
            data={"fact_key": "skills.primary_language"},
            follow_redirects=True,
        )
        assert r.status_code == 200
        assert "removed" in r.text

        fact = fact_repo.get_canonical(candidate_with_facts.id, "skills.primary_language")
        assert fact is None

    def test_get_profile_coverage_json(self, client: TestClient, candidate_with_facts):
        r = client.get("/profile/coverage")
        assert r.status_code == 200
        data = r.json()
        assert "coverage_percentage" in data
        assert "covered_count" in data
        assert "total_required" in data
        assert data["covered_count"] >= 2
