"""
tests/unit/test_calibration_routes.py

Web route tests for /calibration.
"""
from __future__ import annotations

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from ajaa.db.session import init_engine, reset_engine, get_session
from ajaa.web.app import app
from ajaa.db.repositories import candidate as candidate_repo
from ajaa.db.models import CandidateContext


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path, monkeypatch):
    import os
    os.environ["AJAA_TESTING"] = "1"
    monkeypatch.setattr("ajaa.config._settings", None, raising=False)
    monkeypatch.setattr("ajaa.config.Settings.model_config", {"env_prefix": "AJAA_"}, raising=False)
    init_engine(tmp_path / "test_calib_routes.db")
    yield
    reset_engine()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


class TestCalibrationRoutes:
    def test_get_calibration_page(self, client: TestClient):
        r = client.get("/calibration")
        assert r.status_code == 200
        assert "Model Calibration" in r.text
        assert "UNCALIBRATED" in r.text

    def test_complete_calibration(self, client: TestClient):
        r = client.post("/calibration/complete", follow_redirects=True)
        assert r.status_code == 200
        assert "Calibration completed" in r.text

        # Verify candidate DB record updated
        cand = candidate_repo.get_or_none()
        assert cand is not None
        assert cand.calibration_completed is True