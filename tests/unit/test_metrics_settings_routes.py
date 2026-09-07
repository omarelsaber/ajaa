"""
tests/unit/test_metrics_settings_routes.py

Web route tests for /metrics and /settings.
"""
from __future__ import annotations

from pathlib import Path
import pytest
from starlette.testclient import TestClient

from ajaa.db.session import init_engine, reset_engine
from ajaa.web.app import app
from ajaa.db.repositories import candidate as candidate_repo
from ajaa.config import get_settings


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path, monkeypatch):
    import os
    os.environ["AJAA_TESTING"] = "1"
    monkeypatch.setattr("ajaa.config._settings", None, raising=False)
    monkeypatch.setattr("ajaa.config.Settings.model_config", {"env_prefix": "AJAA_"}, raising=False)
    init_engine(tmp_path / "test_metrics_settings.db")
    yield
    reset_engine()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def candidate():
    return candidate_repo.create(display_name="MetricTester")


class TestMetricsAndSettingsRoutes:
    def test_get_metrics_html(self, client: TestClient, candidate):
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "Operational Metrics" in r.text
        assert "Safety Ceiling Headroom" in r.text
        assert "Audit Log Hash Chain" in r.text

    def test_get_metrics_json(self, client: TestClient, candidate):
        r = client.get("/metrics?format=json")
        assert r.status_code == 200
        data = r.json()
        assert "candidate" in data
        assert "jobs" in data
        assert "applications" in data
        assert "audit" in data
        assert data["candidate"]["display_name"] == "MetricTester"

    def test_get_settings_view(self, client: TestClient, candidate):
        r = client.get("/settings")
        assert r.status_code == 200
        assert "Settings &amp; System Policy" in r.text
        assert "Engineering Safety Ceilings" in r.text
        assert "Operational Policy" in r.text
        assert "Greenhouse ATS" in r.text

    def test_update_settings_valid(self, client: TestClient, candidate):
        r = client.post(
            "/settings",
            data={
                "target_daily": "5",
                "review_mode": "first_n_per_connector",
            },
            follow_redirects=True,
        )
        assert r.status_code == 200
        assert "Operational policy updated successfully." in r.text
        settings = get_settings()
        assert settings.policy.operational.max_applications_per_day == 5
        assert settings.policy.review.default_mode == "first_n_per_connector"

    def test_update_settings_reject_ceiling_breach(self, client: TestClient, candidate):
        """Hard invariant: operational target cannot exceed safety ceiling (PRD §26.1)."""
        settings = get_settings()
        ceiling = settings.policy.safety.max_applications_per_day
        over_ceiling = ceiling + 10

        r = client.post(
            "/settings",
            data={
                "target_daily": str(over_ceiling),
                "review_mode": "always",
            },
            follow_redirects=True,
        )
        assert r.status_code == 200
        assert "cannot exceed Safety Ceiling" in r.text
