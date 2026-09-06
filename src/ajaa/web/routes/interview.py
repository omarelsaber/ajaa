"""
src/ajaa/web/routes/interview.py

Interview UI routes.

GET  /interview          — show current question (or complete screen)
POST /interview/answer   — submit an answer (HTMX partial response)
POST /interview/skip     — skip optional question
POST /interview/refuse   — refuse a question

Starlette 1.6+ API: TemplateResponse(request, name, context=dict)
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from ajaa.interview.corpus import get_corpus
from ajaa.interview.session import InterviewSession

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

_QUESTIONS_DIR = (
    Path(__file__).parent.parent.parent.parent.parent / "data" / "questions"
)


def _get_corpus():
    return get_corpus(_QUESTIONS_DIR)


def _get_or_create_candidate_id() -> str:
    """Return existing candidate ID, or create one on first visit."""
    from ajaa.db.repositories import candidate as candidate_repo
    ctx = candidate_repo.get_or_none()
    if ctx is None:
        ctx = candidate_repo.create(display_name="Me")
    return ctx.id


def _progress(session: InterviewSession) -> dict:
    p = session.progress()
    p["pct"] = round(p["covered"] / p["total"] * 100) if p["total"] else 0
    return p


# ── GET /interview ─────────────────────────────────────────────────────────────

@router.get("/interview", response_class=HTMLResponse)
async def interview_page(request: Request):
    candidate_id = _get_or_create_candidate_id()
    session = InterviewSession.start(candidate_id, _get_corpus())
    progress = _progress(session)
    question = session.next_question()

    return templates.TemplateResponse(request, "interview.html", {
        "question": question,
        "complete": question is None,
        "progress": progress,
        "error": None,
    })


# ── POST /interview/answer ────────────────────────────────────────────────────

@router.post("/interview/answer", response_class=HTMLResponse)
async def submit_answer(
    request: Request,
    fact_key: Annotated[str, Form()],
    answer: Annotated[str, Form()] = "",
):
    candidate_id = _get_or_create_candidate_id()
    session = InterviewSession.start(candidate_id, _get_corpus())

    result = session.submit_answer(fact_key, answer)
    progress = _progress(session)

    if not result.accepted:
        # Validation failed — re-show same question with error
        question = _get_corpus().get(fact_key)
        return templates.TemplateResponse(request, "interview_card.html", {
            "question": question,
            "complete": False,
            "progress": progress,
            "error": result.message,
        })

    question = session.next_question()
    return templates.TemplateResponse(request, "interview_card.html", {
        "question": question,
        "complete": question is None,
        "progress": progress,
        "error": None,
    })


# ── POST /interview/skip ──────────────────────────────────────────────────────

@router.post("/interview/skip", response_class=HTMLResponse)
async def skip_question(
    request: Request,
    fact_key: Annotated[str, Form()],
):
    candidate_id = _get_or_create_candidate_id()
    session = InterviewSession.start(candidate_id, _get_corpus())
    session.submit_answer(fact_key, "", skip=True)

    progress = _progress(session)
    question = session.next_question()

    return templates.TemplateResponse(request, "interview_card.html", {
        "question": question,
        "complete": question is None,
        "progress": progress,
        "error": None,
    })


# ── POST /interview/refuse ────────────────────────────────────────────────────

@router.post("/interview/refuse", response_class=HTMLResponse)
async def refuse_question(
    request: Request,
    fact_key: Annotated[str, Form()],
):
    candidate_id = _get_or_create_candidate_id()
    session = InterviewSession.start(candidate_id, _get_corpus())
    session.submit_answer(fact_key, "", refuse=True)

    progress = _progress(session)
    question = session.next_question()

    return templates.TemplateResponse(request, "interview_card.html", {
        "question": question,
        "complete": question is None,
        "progress": progress,
        "error": None,
    })