"""
src/ajaa/web/routes/metrics.py

Operational Metrics & Observability routes (PRD §32 & §28.4).

GET /metrics — JSON / HTML metrics dashboard
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ajaa.config import get_settings
from ajaa.db.models import Application, Job, LLMCallLog
from ajaa.db.repositories import candidate as candidate_repo
from ajaa.db.session import get_session
from ajaa.obs.events import verify_audit_chain
import sqlalchemy as sa

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


def _gather_metrics_dict() -> dict:
    settings = get_settings()
    candidate = candidate_repo.get_or_none()
    candidate_id = candidate.id if candidate else None

    with get_session() as session:
        # Jobs metrics
        total_jobs = session.execute(sa.select(sa.func.count()).select_from(Job)).scalar_one()
        active_jobs = session.execute(
            sa.select(sa.func.count()).select_from(Job).where(Job.is_stale == False)
        ).scalar_one()
        quarantined_jobs = session.execute(
            sa.select(sa.func.count()).select_from(Job).where(Job.quarantined == True)
        ).scalar_one()

        # Applications by state
        app_rows = session.execute(
            sa.select(Application.state, sa.func.count(Application.id))
            .group_by(Application.state)
        ).all()
        app_state_counts = {state: count for state, count in app_rows}

        total_apps = sum(app_state_counts.values())

        # Today's submissions
        today_start = datetime.combine(date.today(), datetime.min.time())
        submitted_today = session.execute(
            sa.select(sa.func.count()).select_from(Application).where(
                Application.state == "SUBMITTED",
                Application.submitted_at >= today_start,
            )
        ).scalar_one()

        # LLM calls summary
        try:
            llm_calls_total = session.execute(
                sa.select(sa.func.count()).select_from(LLMCallLog)
            ).scalar_one()
            llm_cost_total = session.execute(
                sa.select(sa.func.sum(LLMCallLog.cost_usd)).select_from(LLMCallLog)
            ).scalar_one() or 0.0
        except Exception:
            llm_calls_total = 0
            llm_cost_total = 0.0

    # Verify audit chain integrity
    audit_log_path = settings.data_dir / "logs" / "audit_events.jsonl"
    audit_ok = verify_audit_chain(audit_log_path) if audit_log_path.exists() else True

    daily_ceiling = settings.policy.safety.max_applications_per_day
    headroom_remaining = max(0, daily_ceiling - submitted_today)

    return {
        "candidate": {
            "id": candidate_id,
            "display_name": candidate.display_name if candidate else "None",
            "is_calibrated": bool(candidate.calibration_completed) if candidate else False,
        },
        "jobs": {
            "total": total_jobs,
            "active": active_jobs,
            "quarantined": quarantined_jobs,
        },
        "applications": {
            "total": total_apps,
            "by_state": app_state_counts,
            "submitted_today": submitted_today,
            "daily_ceiling": daily_ceiling,
            "headroom_remaining": headroom_remaining,
        },
        "audit": {
            "hash_chain_verified": audit_ok,
            "log_path": str(audit_log_path),
        },
        "llm": {
            "total_calls": llm_calls_total,
            "total_cost_usd": round(llm_cost_total, 4),
        },
    }


@router.get("/metrics")
async def get_metrics(request: Request, format: str | None = None):
    metrics = _gather_metrics_dict()

    accept_header = request.headers.get("accept", "")
    if format == "json" or "application/json" in accept_header:
        return JSONResponse(content=metrics)

    return templates.TemplateResponse(request, "metrics.html", {
        "m": metrics,
    })
