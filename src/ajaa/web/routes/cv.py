"""
src/ajaa/web/routes/cv.py

CV upload and management routes.

POST /cv/upload   — multipart PDF upload (HTMX-friendly)
GET  /cv          — list uploaded CVs with extraction status
DELETE /cv/{cv_id} — deactivate a CV
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

_MAX_FILE_SIZE_MB = 10
_MAX_FILE_SIZE_BYTES = _MAX_FILE_SIZE_MB * 1024 * 1024


def _get_or_create_candidate_id() -> str:
    from ajaa.db.repositories import candidate as candidate_repo
    ctx = candidate_repo.get_or_none()
    if ctx is None:
        ctx = candidate_repo.create(display_name="Me")
    return ctx.id


def _list_cvs(candidate_id: str) -> list:
    from ajaa.db.session import get_session
    from ajaa.db.models import CV
    import sqlalchemy as sa

    with get_session() as session:
        rows = session.execute(
            sa.select(CV)
            .where(CV.candidate_id == candidate_id, CV.is_active == True)
            .order_by(CV.created_at.desc())
        ).scalars().all()
        return [
            {
                "id": r.id,
                "filename": r.filename,
                "label": r.label or r.filename,
                "page_count": r.page_count,
                "char_count": r.char_count,
                "extraction_status": r.extraction_status,
                "uploaded_at": r.uploaded_at.strftime("%Y-%m-%d %H:%M") if r.uploaded_at else "",
            }
            for r in rows
        ]


# ── GET /cv ───────────────────────────────────────────────────────────────────

@router.get("/cv", response_class=HTMLResponse)
async def cv_list(request: Request):
    candidate_id = _get_or_create_candidate_id()
    cvs = _list_cvs(candidate_id)

    return templates.TemplateResponse(request, "cv.html", {
        "cvs": cvs,
        "error": None,
        "success": None,
    })


# ── POST /cv/upload ───────────────────────────────────────────────────────────

@router.post("/cv/upload", response_class=HTMLResponse)
async def cv_upload(request: Request, file: UploadFile = File(...)):
    candidate_id = _get_or_create_candidate_id()

    # Validate file type
    filename = file.filename or "upload.pdf"
    if not filename.lower().endswith(".pdf"):
        cvs = _list_cvs(candidate_id)
        return templates.TemplateResponse(request, "cv.html", {
            "cvs": cvs,
            "error": "Only PDF files are accepted.",
            "success": None,
        })

    # Read bytes with size guard
    data = await file.read(_MAX_FILE_SIZE_BYTES + 1)
    if len(data) > _MAX_FILE_SIZE_BYTES:
        cvs = _list_cvs(candidate_id)
        return templates.TemplateResponse(request, "cv.html", {
            "cvs": cvs,
            "error": f"File too large. Maximum size is {_MAX_FILE_SIZE_MB} MB.",
            "success": None,
        })

    # Ingest (dedup + text extraction)
    try:
        from ajaa.cv.ingester import ingest_pdf_bytes
        result = ingest_pdf_bytes(candidate_id, data, filename)
    except ValueError as exc:
        cvs = _list_cvs(candidate_id)
        return templates.TemplateResponse(request, "cv.html", {
            "cvs": cvs,
            "error": f"Invalid PDF: {exc}",
            "success": None,
        })
    except RuntimeError as exc:
        cvs = _list_cvs(candidate_id)
        return templates.TemplateResponse(request, "cv.html", {
            "cvs": cvs,
            "error": str(exc),
            "success": None,
        })

    # Trigger extraction (best-effort, LLM may be unavailable)
    _trigger_extraction_bg(candidate_id, result.cv_id, result)

    msg = (
        f"'{filename}' already uploaded (duplicate detected)."
        if result.was_duplicate
        else f"'{filename}' uploaded ({result.page_count} pages, "
             f"{result.char_count:,} chars). Extraction queued."
    )

    cvs = _list_cvs(candidate_id)
    return templates.TemplateResponse(request, "cv.html", {
        "cvs": cvs,
        "error": None,
        "success": msg,
    })


# ── DELETE /cv/{cv_id} ────────────────────────────────────────────────────────

@router.post("/cv/{cv_id}/deactivate", response_class=HTMLResponse)
async def cv_deactivate(request: Request, cv_id: str):
    candidate_id = _get_or_create_candidate_id()

    from ajaa.db.session import get_session
    from ajaa.db.models import CV
    import sqlalchemy as sa

    with get_session() as session:
        session.execute(
            sa.update(CV)
            .where(CV.id == cv_id, CV.candidate_id == candidate_id)
            .values(is_active=False)
        )
        session.commit()

    cvs = _list_cvs(candidate_id)
    return templates.TemplateResponse(request, "cv.html", {
        "cvs": cvs,
        "error": None,
        "success": "CV removed.",
    })


# ── Background extraction helper ──────────────────────────────────────────────

def _trigger_extraction_bg(candidate_id: str, cv_id: str, ingest_result) -> None:
    """
    Trigger CV extraction synchronously (simplified — no task queue yet).
    If LLM is unavailable, the CV stays in PENDING state for later retry.
    """
    if ingest_result.was_duplicate:
        return  # Already extracted

    from ajaa.db.session import get_session
    from ajaa.db.models import CV
    from ajaa.cv.extractor import extract_cv_facts
    import sqlalchemy as sa

    # Read raw_text from DB
    with get_session() as session:
        cv = session.execute(
            sa.select(CV).where(CV.id == cv_id)
        ).scalars().first()
        if cv is None:
            return
        raw_text = cv.raw_text or ""
        content_hash = cv.content_hash

    if not raw_text:
        return

    # Update status to EXTRACTING
    with get_session() as session:
        session.execute(
            sa.update(CV).where(CV.id == cv_id).values(extraction_status="EXTRACTING")
        )
        session.commit()

    try:
        extract_cv_facts(candidate_id, cv_id, raw_text, content_hash)
        status = "DONE"
    except Exception:
        status = "FAILED"

    with get_session() as session:
        from datetime import datetime, timezone
        session.execute(
            sa.update(CV).where(CV.id == cv_id).values(
                extraction_status=status,
                extracted_at=datetime.now(timezone.utc),
            )
        )
        session.commit()