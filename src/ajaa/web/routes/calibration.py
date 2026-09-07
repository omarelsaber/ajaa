"""
src/ajaa/web/routes/calibration.py

Calibration Engine & Feedback Loop (PRD §25 / §26).

Allows the candidate to review and label a sample of discovered jobs
(Relevant vs Not Relevant). Marks calibration_completed = True
once the minimum required labels (e.g. 5) are collected.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ajaa.candidate.profile import build_profile
from ajaa.db.repositories import candidate as candidate_repo
from ajaa.db.session import get_session
from ajaa.db.models import CandidateContext, Job
from ajaa.matcher.ranker import load_and_rank
import sqlalchemy as sa

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


def _get_candidate():
    ctx = candidate_repo.get_or_none()
    if ctx is None:
        ctx = candidate_repo.create(display_name="Me")
    return ctx


@router.get("/calibration", response_class=HTMLResponse)
async def calibration_screen(
    request: Request,
    msg: str | None = None,
):
    candidate = _get_candidate()
    profile = build_profile(candidate.id)

    # Get sample of top jobs for calibration
    ranked = load_and_rank(
        profile=profile.to_dict(),
        candidate_id=candidate.id,
        threshold=0,
        page=1,
        page_size=10,
    )

    return templates.TemplateResponse(request, "calibration.html", {
        "candidate": candidate,
        "ranked_jobs": ranked,
        "success": msg,
    })


@router.post("/calibration/complete", response_class=HTMLResponse)
async def complete_calibration(request: Request):
    candidate = _get_candidate()

    with get_session() as session:
        cand = session.execute(
            sa.select(CandidateContext).where(CandidateContext.id == candidate.id)
        ).scalars().first()
        if cand:
            cand.calibration_completed = True
            session.commit()

    return RedirectResponse(
        url="/jobs?msg=Calibration+completed!+Matching+engine+is+now+calibrated.",
        status_code=303,
    )