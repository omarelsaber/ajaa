"""
tests/unit/test_cv_routes.py

CV web route tests.
"""
from __future__ import annotations

import io
from pathlib import Path

import pymupdf
import pytest
from starlette.testclient import TestClient

from ajaa.db.session import init_engine, reset_engine
from ajaa.web.app import app


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path, monkeypatch):
    import os
    os.environ["AJAA_TESTING"] = "1"
    monkeypatch.setattr("ajaa.config._settings", None, raising=False)
    monkeypatch.setattr("ajaa.config.Settings.model_config", {"env_prefix": "AJAA_"}, raising=False)
    init_engine(tmp_path / "test_routes_cv.db")

    # Patch settings so data_dir = tmp_path
    from unittest.mock import MagicMock
    settings = MagicMock()
    settings.data_dir = tmp_path
    (tmp_path / "cvs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("ajaa.cv.ingester.get_settings", lambda: settings)
    yield
    reset_engine()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def minimal_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 100), "Jane Smith\njane@example.com\nSenior Engineer")
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


class TestCvList:
    def test_get_cv_page_200(self, client: TestClient) -> None:
        r = client.get("/cv")
        assert r.status_code == 200
        assert "Upload" in r.text

    def test_empty_state_shown(self, client: TestClient) -> None:
        r = client.get("/cv")
        assert "No CVs uploaded yet" in r.text


class TestCvUpload:
    def test_upload_valid_pdf(self, client: TestClient, minimal_pdf: bytes) -> None:
        r = client.post(
            "/cv/upload",
            files={"file": ("my_cv.pdf", minimal_pdf, "application/pdf")},
        )
        assert r.status_code == 200
        assert "my_cv.pdf" in r.text or "uploaded" in r.text.lower()

    def test_upload_non_pdf_rejected(self, client: TestClient) -> None:
        r = client.post(
            "/cv/upload",
            files={"file": ("resume.docx", b"fake docx content", "application/octet-stream")},
        )
        assert r.status_code == 200
        assert "Only PDF" in r.text

    def test_upload_duplicate_detected(self, client: TestClient, minimal_pdf: bytes) -> None:
        client.post("/cv/upload", files={"file": ("cv.pdf", minimal_pdf, "application/pdf")})
        r = client.post("/cv/upload", files={"file": ("cv_copy.pdf", minimal_pdf, "application/pdf")})
        assert r.status_code == 200
        assert "duplicate" in r.text.lower() or "already" in r.text.lower()

    def test_cv_appears_in_list_after_upload(self, client: TestClient, minimal_pdf: bytes) -> None:
        client.post("/cv/upload", files={"file": ("listed.pdf", minimal_pdf, "application/pdf")})
        r = client.get("/cv")
        assert "listed.pdf" in r.text