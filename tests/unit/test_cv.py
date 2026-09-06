"""
tests/unit/test_cv.py

CV ingestion and extraction tests.

Covers:
  - PDF text extraction from bytes (valid PDF)
  - Duplicate detection (same hash = same content)
  - IngestResult fields (cv_id, was_duplicate, page_count, char_count)
  - Content-addressed caching in ingester
  - extract_text_from_bytes rejects non-PDF
  - compute_sha256 determinism
  - _parse_llm_response handles clean JSON, fenced JSON, broken JSON
  - ALLOWED_CV_KEYS boundary enforcement
  - ExtractResult.llm_unavailable when LLM raises
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pymupdf

from ajaa.db.session import init_engine, reset_engine


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path):
    init_engine(tmp_path / "test_cv.db")
    yield
    reset_engine()


@pytest.fixture
def candidate_id(tmp_path: Path) -> str:
    from ajaa.db.repositories import candidate as candidate_repo
    return candidate_repo.create(display_name="CV Test Candidate").id


@pytest.fixture
def minimal_pdf_bytes() -> bytes:
    """Create a minimal valid PDF with one page of text using PyMuPDF."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((50, 100), "John Doe\njohn@example.com\nSoftware Engineer\n5 years experience")
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


@pytest.fixture
def ajaa_settings_tmp(tmp_path: Path, monkeypatch):
    """Patch settings so data_dir = tmp_path."""
    from unittest.mock import MagicMock
    settings = MagicMock()
    settings.data_dir = tmp_path
    (tmp_path / "cvs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("ajaa.cv.ingester.get_settings", lambda: settings)
    return settings


# ── Text extraction ───────────────────────────────────────────────────────────

class TestPdfTextExtraction:

    def test_extract_bytes_returns_text(self, minimal_pdf_bytes: bytes) -> None:
        from ajaa.cv.ingester import extract_text_from_bytes
        text = extract_text_from_bytes(minimal_pdf_bytes, filename="test.pdf")
        assert "John Doe" in text
        assert len(text) > 10

    def test_extract_invalid_bytes_raises(self) -> None:
        from ajaa.cv.ingester import extract_text_from_bytes
        with pytest.raises(ValueError, match="Cannot parse PDF"):
            extract_text_from_bytes(b"not a pdf", filename="bad.pdf")

    def test_extract_multipage_separates_with_formfeed(self) -> None:
        from ajaa.cv.ingester import extract_text_from_bytes
        doc = pymupdf.open()
        doc.new_page().insert_text((50, 100), "Page one content here")
        doc.new_page().insert_text((50, 100), "Page two content here")
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()
        text = extract_text_from_bytes(buf.getvalue())
        assert "\f" in text  # pages separated by form-feed


# ── SHA-256 ───────────────────────────────────────────────────────────────────

class TestComputeHash:

    def test_deterministic(self) -> None:
        from ajaa.cv.ingester import compute_sha256
        data = b"hello world"
        assert compute_sha256(data) == compute_sha256(data)

    def test_different_data_different_hash(self) -> None:
        from ajaa.cv.ingester import compute_sha256
        assert compute_sha256(b"aaa") != compute_sha256(b"bbb")

    def test_returns_64_hex_chars(self) -> None:
        from ajaa.cv.ingester import compute_sha256
        h = compute_sha256(b"test")
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


# ── Ingestion ─────────────────────────────────────────────────────────────────

class TestIngestPdf:

    def test_ingest_new_cv(
        self, candidate_id: str, minimal_pdf_bytes: bytes, ajaa_settings_tmp
    ) -> None:
        from ajaa.cv.ingester import ingest_pdf_bytes
        result = ingest_pdf_bytes(candidate_id, minimal_pdf_bytes, "cv.pdf")
        assert result.cv_id is not None
        assert result.was_duplicate is False
        assert result.char_count > 0
        assert result.page_count >= 1

    def test_ingest_same_content_is_duplicate(
        self, candidate_id: str, minimal_pdf_bytes: bytes, ajaa_settings_tmp
    ) -> None:
        from ajaa.cv.ingester import ingest_pdf_bytes
        r1 = ingest_pdf_bytes(candidate_id, minimal_pdf_bytes, "cv.pdf")
        r2 = ingest_pdf_bytes(candidate_id, minimal_pdf_bytes, "cv_copy.pdf")
        assert r1.cv_id == r2.cv_id
        assert r2.was_duplicate is True

    def test_ingest_different_content_is_new(
        self, candidate_id: str, minimal_pdf_bytes: bytes, ajaa_settings_tmp
    ) -> None:
        from ajaa.cv.ingester import ingest_pdf_bytes, compute_sha256
        doc = pymupdf.open()
        doc.new_page().insert_text((50, 100), "Completely different CV content here 12345")
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()
        other_bytes = buf.getvalue()

        r1 = ingest_pdf_bytes(candidate_id, minimal_pdf_bytes, "cv1.pdf")
        r2 = ingest_pdf_bytes(candidate_id, other_bytes, "cv2.pdf")
        assert r1.cv_id != r2.cv_id
        assert r2.was_duplicate is False

    def test_ingested_cv_stored_in_db(
        self, candidate_id: str, minimal_pdf_bytes: bytes, ajaa_settings_tmp
    ) -> None:
        from ajaa.cv.ingester import ingest_pdf_bytes
        from ajaa.db.session import get_session
        from ajaa.db.models import CV
        import sqlalchemy as sa

        result = ingest_pdf_bytes(candidate_id, minimal_pdf_bytes, "cv.pdf")
        with get_session() as session:
            cv = session.execute(
                sa.select(CV).where(CV.id == result.cv_id)
            ).scalars().first()
            assert cv is not None
            assert cv.filename == "cv.pdf"
            assert cv.raw_text is not None
            assert "John" in cv.raw_text


# ── LLM response parser ────────────────────────────────────────────────────────

class TestParseLlmResponse:

    def _parse(self, text: str):
        from ajaa.cv.extractor import _parse_llm_response
        return _parse_llm_response(text)

    def test_clean_json(self) -> None:
        payload = json.dumps({"facts": [{"key": "personal.name.full", "value": "Alice", "confidence": "HIGH", "inferred": False}]})
        result = self._parse(payload)
        assert result is not None
        assert len(result) == 1
        assert result[0]["key"] == "personal.name.full"

    def test_fenced_json(self) -> None:
        text = '```json\n{"facts": [{"key": "personal.email.primary", "value": "a@b.com", "confidence": "HIGH", "inferred": false}]}\n```'
        result = self._parse(text)
        assert result is not None
        assert result[0]["value"] == "a@b.com"

    def test_broken_json_returns_none(self) -> None:
        result = self._parse("this is not json at all")
        assert result is None

    def test_empty_facts_array(self) -> None:
        result = self._parse('{"facts": []}')
        assert result == []


# ── Key boundary enforcement ──────────────────────────────────────────────────

class TestAllowedKeys:

    def test_disallowed_key_skipped(
        self, candidate_id: str, minimal_pdf_bytes: bytes, ajaa_settings_tmp
    ) -> None:
        from ajaa.cv.ingester import ingest_pdf_bytes
        from ajaa.cv.extractor import ExtractResult, _write_facts
        from ajaa.db.repositories import fact as fact_repo

        ingest_result = ingest_pdf_bytes(candidate_id, minimal_pdf_bytes, "cv.pdf")

        raw_facts = [
            {"key": "personal.name.full", "value": "Alice", "confidence": "HIGH", "inferred": False},
            {"key": "hacker.injection.payload", "value": "DROP TABLE facts", "confidence": "HIGH", "inferred": False},
        ]
        result = ExtractResult(cv_id=ingest_result.cv_id, candidate_id=candidate_id)
        _write_facts(candidate_id, ingest_result.cv_id, raw_facts, fact_repo, result)

        assert result.facts_written == 1
        assert result.facts_skipped == 1

        # Verify the injected key was NOT written
        fact = fact_repo.get_canonical(candidate_id, "hacker.injection.payload")
        assert fact is None


# ── LLM unavailable ───────────────────────────────────────────────────────────

class TestLlmUnavailable:

    def test_extract_returns_llm_unavailable_on_error(
        self, candidate_id: str, minimal_pdf_bytes: bytes, ajaa_settings_tmp
    ) -> None:
        from ajaa.cv.ingester import ingest_pdf_bytes
        from ajaa.cv.extractor import extract_cv_facts

        ingest_result = ingest_pdf_bytes(candidate_id, minimal_pdf_bytes, "cv.pdf")

        with patch("ajaa.llm.gateway.call_llm", side_effect=Exception("401 unauthorized")):
            result = extract_cv_facts(
                candidate_id=candidate_id,
                cv_id=ingest_result.cv_id,
                raw_text="John Doe john@example.com",
                content_hash=ingest_result.content_hash,
            )

        assert result.llm_unavailable is True
        assert result.facts_written == 0
        assert "401" in (result.error or "")