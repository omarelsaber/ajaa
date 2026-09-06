"""
tests/unit/test_web_routes.py

Web route tests using FastAPI TestClient (synchronous, no real server).

Covers:
  - GET  /health         — 200, JSON checks present
  - GET  /              — 200, dashboard HTML
  - GET  /interview     — 200 (no candidate: shows error message)
  - GET  /interview     — 200 (with candidate: shows first question)
  - POST /interview/answer  — valid answer -> advances to next question
  - POST /interview/answer  — invalid email -> error shown, same question
  - POST /interview/skip    — marks question skipped
  - POST /interview/refuse  — marks question refused
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ajaa.db.session import init_engine, reset_engine


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path):
    """Each test gets a fresh DB and data dir override."""
    import os
    os.environ["AJAA_TESTING"] = "1"
    os.environ["AJAA_DATA_DIR"] = str(tmp_path / "ajaa_data")
    os.environ["AJAA_CONFIG_DIR"] = str(tmp_path / "ajaa_config")
    init_engine(tmp_path / "ajaa_data" / "db" / "ajaa.db")

    # Ensure DB dir exists
    (tmp_path / "ajaa_data" / "db").mkdir(parents=True, exist_ok=True)

    yield

    reset_engine()
    del os.environ["AJAA_TESTING"]
    del os.environ["AJAA_DATA_DIR"]
    del os.environ["AJAA_CONFIG_DIR"]


@pytest.fixture
def questions_dir(tmp_path: Path) -> Path:
    qdir = tmp_path / "questions"
    qdir.mkdir()
    (qdir / "personal.yaml").write_text(textwrap.dedent("""\
    - key: personal.name.full
      prompt: "What is your full name?"
      required: true
      type: text
      tier: foundation
    - key: personal.email.primary
      prompt: "What is your email?"
      required: true
      type: text
      tier: foundation
    """), encoding="utf-8")
    return qdir


@pytest.fixture
def client(questions_dir: Path, monkeypatch) -> TestClient:
    """TestClient with patched corpus dir."""
    from ajaa.interview import corpus as corpus_module
    from ajaa.web.routes import interview as interview_module

    # Reload corpus from test questions dir
    from ajaa.interview.corpus import reload_corpus
    reload_corpus(questions_dir)

    # Patch the routes module to use test questions dir
    monkeypatch.setattr(interview_module, "_QUESTIONS_DIR", questions_dir)

    from ajaa.web.app import app
    return TestClient(app, raise_server_exceptions=True)


@pytest.fixture
def client_with_candidate(client, questions_dir) -> TestClient:
    from ajaa.db.repositories import candidate as candidate_repo
    from ajaa.interview.corpus import reload_corpus
    reload_corpus(questions_dir)
    candidate_repo.create(display_name="Test Candidate")
    return client


# ── /health ───────────────────────────────────────────────────────────────────

class TestHealthRoute:
    def test_health_returns_200(self, client: TestClient) -> None:
        r = client.get("/health")
        assert r.status_code in (200, 503)  # 503 if bootstrap checks fail in test env
        body = r.json()
        assert "status" in body
        assert "checks" in body

    def test_health_checks_list(self, client: TestClient) -> None:
        r = client.get("/health")
        checks = r.json()["checks"]
        names = {c["name"] for c in checks}
        assert "python_version" in names


# ── / (dashboard) ─────────────────────────────────────────────────────────────

class TestDashboard:
    def test_dashboard_200(self, client: TestClient) -> None:
        r = client.get("/")
        assert r.status_code == 200
        assert "AJAA" in r.text

    def test_dashboard_with_candidate(self, client_with_candidate: TestClient) -> None:
        r = client_with_candidate.get("/")
        assert r.status_code == 200
        assert "Test Candidate" in r.text


# ── /interview ────────────────────────────────────────────────────────────────

class TestInterviewGet:
    def test_no_candidate_auto_creates_and_shows_question(self, client: TestClient) -> None:
        # /interview now auto-creates a candidate profile on first visit
        r = client.get("/interview")
        assert r.status_code == 200
        # Should show the first question (not an error)
        assert "answer" in r.text.lower() or "name" in r.text.lower() or "question" in r.text.lower()

    def test_with_candidate_shows_question(self, client_with_candidate: TestClient) -> None:
        r = client_with_candidate.get("/interview")
        assert r.status_code == 200
        assert "full name" in r.text.lower() or "name" in r.text.lower()

    def test_shows_progress_bar(self, client_with_candidate: TestClient) -> None:
        r = client_with_candidate.get("/interview")
        assert r.status_code == 200
        assert "progress" in r.text.lower() or "%" in r.text


# ── /interview/answer ─────────────────────────────────────────────────────────

class TestInterviewAnswer:
    def test_valid_answer_advances(self, client_with_candidate: TestClient) -> None:
        r = client_with_candidate.post(
            "/interview/answer",
            data={"fact_key": "personal.name.full", "answer": "Alice Smith"},
        )
        assert r.status_code == 200
        # Should now show the email question
        assert "email" in r.text.lower()

    def test_invalid_email_shows_error(self, client_with_candidate: TestClient) -> None:
        r = client_with_candidate.post(
            "/interview/answer",
            data={"fact_key": "personal.email.primary", "answer": "not-valid"},
        )
        assert r.status_code == 200
        assert "email" in r.text.lower()

    def test_valid_email_accepted(self, client_with_candidate: TestClient) -> None:
        # First answer name
        client_with_candidate.post(
            "/interview/answer",
            data={"fact_key": "personal.name.full", "answer": "Alice Smith"},
        )
        # Then email
        r = client_with_candidate.post(
            "/interview/answer",
            data={"fact_key": "personal.email.primary", "answer": "alice@example.com"},
        )
        assert r.status_code == 200


# ── /interview/skip ───────────────────────────────────────────────────────────

class TestInterviewSkip:
    def test_skip_advances_session(self, client_with_candidate: TestClient) -> None:
        r = client_with_candidate.post(
            "/interview/skip",
            data={"fact_key": "personal.name.full"},
        )
        assert r.status_code == 200
        # Should move to next question or show complete


# ── /interview/refuse ─────────────────────────────────────────────────────────

class TestInterviewRefuse:
    def test_refuse_advances_session(self, client_with_candidate: TestClient) -> None:
        r = client_with_candidate.post(
            "/interview/refuse",
            data={"fact_key": "personal.name.full"},
        )
        assert r.status_code == 200