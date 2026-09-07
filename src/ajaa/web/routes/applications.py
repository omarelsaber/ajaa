"""
src/ajaa/web/routes/applications.py

Application tracker, review gates, and submission routes.

GET  /applications            — list applications (queued, ready for review, submitted)
POST /applications/{id}/prepare — prepare answers from profile
POST /applications/{id}/approve — approve application for submission
POST /applications/{id}/submit  — submit application
POST /applications/{id}/reject  — reject/discard application
"""
from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ajaa.application.state_machine import (
    ApplicationState,
    approve_application,
    prepare_application,
    submit_application,
)
from ajaa.db.repositories import candidate as candidate_repo
from ajaa.db.session import get_session
from ajaa.db.models import Application, ApplicationAnswer, AuditEvent, Job
import sqlalchemy as sa

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


def _get_candidate_id():
    ctx = candidate_repo.get_or_none()
    if ctx is None:
        ctx = candidate_repo.create(display_name="Me")
    return ctx.id


@router.get("/applications", response_class=HTMLResponse)
async def list_applications(
    request: Request,
    msg: str | None = None,
    err: str | None = None,
):
    candidate_id = _get_candidate_id()

    with get_session() as session:
        # Load all applications for candidate along with their Job and Answers
        apps = session.execute(
            sa.select(Application)
            .where(Application.candidate_id == candidate_id)
            .order_by(Application.created_at.desc())
        ).scalars().all()

        app_list = []
        for app in apps:
            job = session.execute(sa.select(Job).where(Job.id == app.job_id)).scalars().first()
            answers = session.execute(
                sa.select(ApplicationAnswer).where(ApplicationAnswer.application_id == app.id)
            ).scalars().all()

            events = session.execute(
                sa.select(AuditEvent)
                .where(AuditEvent.application_id == app.id)
                .order_by(AuditEvent.occurred_at.asc())
            ).scalars().all()

            app_list.append({
                "id": app.id,
                "state": app.state,
                "created_at": app.created_at.strftime("%Y-%m-%d %H:%M") if app.created_at else "",
                "submitted_at": app.submitted_at.strftime("%Y-%m-%d %H:%M") if app.submitted_at else None,
                "review_decision": app.review_decision,
                "job": {
                    "id": job.id if job else "",
                    "title": job.title if job else "Untitled",
                    "company": job.company if job else "Unknown",
                    "apply_url": job.apply_url if job else "#",
                    "location": job.location if job else "",
                } if job else None,
                "answers": [
                    {
                        "field_label": a.field_label,
                        "answer_value": a.answer_value,
                        "confidence": a.confidence,
                        "source": a.answer_source,
                    }
                    for a in answers
                ],
                "audit_events": [
                    {
                        "time": e.occurred_at.strftime("%H:%M:%S"),
                        "event_type": e.event_type,
                        "transition": f"{e.from_state} → {e.to_state}" if e.from_state else e.to_state,
                    }
                    for e in events
                ],
            })

    return templates.TemplateResponse(request, "applications.html", {
        "applications": app_list,
        "success": msg,
        "error": err,
    })


@router.post("/applications/{app_id}/prepare", response_class=HTMLResponse)
async def prepare_app_route(request: Request, app_id: str):
    try:
        res = prepare_application(app_id)
        msg = f"Application answers prepared: {res.resolved_count} resolved, {res.needs_user_count} need attention."
    except Exception as e:
        return RedirectResponse(url=f"/applications?err={e}", status_code=303)

    return RedirectResponse(url=f"/applications?msg={msg}", status_code=303)


@router.post("/applications/{app_id}/approve", response_class=HTMLResponse)
async def approve_app_route(request: Request, app_id: str):
    try:
        approve_application(app_id)
        msg = "Application approved by user."
    except Exception as e:
        return RedirectResponse(url=f"/applications?err={e}", status_code=303)

    return RedirectResponse(url=f"/applications?msg={msg}", status_code=303)


@router.post("/applications/{app_id}/submit", response_class=HTMLResponse)
async def submit_app_route(request: Request, app_id: str):
    try:
        submit_application(app_id)
        msg = "Application marked as SUBMITTED."
    except Exception as e:
        return RedirectResponse(url=f"/applications?err={e}", status_code=303)

    return RedirectResponse(url=f"/applications?msg={msg}", status_code=303)


@router.post("/applications/{app_id}/reject", response_class=HTMLResponse)
async def reject_app_route(request: Request, app_id: str):
    with get_session() as session:
        app = session.execute(
            sa.select(Application).where(Application.id == app_id)
        ).scalars().first()
        if app:
            app.previous_state = app.state
            app.state = ApplicationState.REJECTED.value
            app.review_decision = "REJECTED"
            session.commit()

    return RedirectResponse(url="/applications?msg=Application+discarded.", status_code=303)