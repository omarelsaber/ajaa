"""
src/ajaa/cv/ingester.py

CV ingestion pipeline.

Responsibilities:
  1. Accept a PDF file path (or bytes)
  2. Compute SHA-256 content hash (content-addressed identity)
  3. Check if this exact content already exists in the `cvs` table
  4. If new: extract text via PyMuPDF, store in cvs table
  5. Return a CV record (existing or new)

Content-addressed dedup rule:
  Same SHA-256 hash = same file = no re-extraction needed.
  Different hash = new content = must extract.

Does NOT call the LLM — that is extractor.py's job.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pymupdf  # PyMuPDF

from ajaa.config import get_settings


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text_from_pdf(path: Path) -> str:
    """
    Extract all text from a PDF using PyMuPDF.

    Returns a single string with pages separated by form-feed characters.
    Raises ValueError if the file is not a valid PDF.
    Raises RuntimeError if text extraction yields nothing (scanned image PDF).
    """
    try:
        doc = pymupdf.open(str(path))
    except Exception as exc:
        raise ValueError(f"Cannot open PDF: {path.name}") from exc

    pages: list[str] = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            pages.append(text.strip())
    doc.close()

    if not pages:
        raise RuntimeError(
            f"No text extracted from '{path.name}'. "
            "The file may be a scanned image PDF. "
            "Please use a text-based PDF or run OCR first."
        )

    return "\f".join(pages)  # form-feed between pages


def extract_text_from_bytes(data: bytes, filename: str = "upload.pdf") -> str:
    """Extract text from in-memory PDF bytes."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise ValueError(f"Cannot parse PDF bytes for '{filename}'") from exc

    pages: list[str] = []
    for page in doc:
        text = page.get_text("text")
        if text.strip():
            pages.append(text.strip())
    doc.close()

    if not pages:
        raise RuntimeError(
            f"No text extracted from '{filename}'. "
            "The file may be a scanned image PDF."
        )

    return "\f".join(pages)


# ── Hash ──────────────────────────────────────────────────────────────────────

def compute_sha256(data: bytes) -> str:
    """Return hex SHA-256 of raw bytes."""
    return hashlib.sha256(data).hexdigest()


# ── Ingest ────────────────────────────────────────────────────────────────────

@dataclass
class IngestResult:
    cv_id: str
    content_hash: str
    filename: str
    was_duplicate: bool      # True = same content already in DB
    char_count: int          # length of extracted text
    page_count: int


def ingest_pdf(
    candidate_id: str,
    path: Path,
    *,
    label: str = "",
) -> IngestResult:
    """
    Ingest a CV PDF from disk.

    - Computes SHA-256 of raw bytes.
    - If same hash already exists for this candidate: returns existing record.
    - Otherwise: extracts text, stores in DB, returns new record.

    label: optional user-facing label (e.g. "My CV 2025")
    """
    raw = path.read_bytes()
    return _ingest_bytes(candidate_id, raw, filename=path.name, label=label)


def ingest_pdf_bytes(
    candidate_id: str,
    data: bytes,
    filename: str,
    *,
    label: str = "",
) -> IngestResult:
    """Ingest a CV PDF from in-memory bytes (e.g. HTTP upload)."""
    return _ingest_bytes(candidate_id, data, filename=filename, label=label)


def _ingest_bytes(
    candidate_id: str,
    raw: bytes,
    filename: str,
    label: str,
) -> IngestResult:
    from ajaa.db.models import CV
    from ajaa.db.session import get_session
    import sqlalchemy as sa

    content_hash = compute_sha256(raw)

    with get_session() as session:
        # Check for existing row with same hash for this candidate
        existing = session.execute(
            sa.select(CV).where(
                CV.candidate_id == candidate_id,
                CV.content_hash == content_hash,
            )
        ).scalars().first()

        if existing is not None:
            session.expunge(existing)
            return IngestResult(
                cv_id=existing.id,
                content_hash=content_hash,
                filename=existing.filename,
                was_duplicate=True,
                char_count=len(existing.raw_text or ""),
                page_count=existing.page_count,
            )

        # New content — extract text
        raw_text = extract_text_from_bytes(raw, filename=filename)
        page_count = raw_text.count("\f") + 1

        # Save to data/cvs/ directory
        settings = get_settings()
        cvs_dir = settings.data_dir / "cvs"
        cvs_dir.mkdir(parents=True, exist_ok=True)
        dest = cvs_dir / f"{content_hash[:12]}_{filename}"
        dest.write_bytes(raw)

        # Persist to DB
        now = datetime.now(timezone.utc)
        cv = CV(
            candidate_id=candidate_id,
            filename=filename,
            label=label or filename,
            file_path=str(dest),
            content_hash=content_hash,
            raw_text=raw_text,
            page_count=page_count,
            char_count=len(raw_text),
            created_at=now,
            updated_at=now,
        )
        session.add(cv)
        session.flush()
        cv_id = cv.id
        session.commit()

    return IngestResult(
        cv_id=cv_id,
        content_hash=content_hash,
        filename=filename,
        was_duplicate=False,
        char_count=len(raw_text),
        page_count=page_count,
    )