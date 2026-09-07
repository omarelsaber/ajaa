"""
src/ajaa/web/app.py

FastAPI application — Starlette 1.6+ TemplateResponse(request, name, context)
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from ajaa.web.routes.interview import router as interview_router
from ajaa.web.routes.cv import router as cv_router
from ajaa.web.routes.jobs import router as jobs_router
from ajaa.web.routes.applications import router as applications_router
from ajaa.web.routes.calibration import router as calibration_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB engine on startup. Shutdown: dispose engine."""
    from ajaa.config import get_settings
    from ajaa.db.session import init_engine, reset_engine

    settings = get_settings()
    db_path = settings.data_dir / "db" / "ajaa.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_engine(db_path)
    yield
    reset_engine()


app = FastAPI(
    title="AJAA",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

app.include_router(interview_router)
app.include_router(cv_router)
app.include_router(jobs_router)
app.include_router(applications_router)
app.include_router(calibration_router)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    from ajaa.db.repositories.candidate import get_or_none
    from ajaa.db.repositories import fact as fact_repo
    from ajaa.interview.corpus import get_corpus

    questions_dir = Path(__file__).parent.parent.parent.parent / "data" / "questions"
    corpus = get_corpus(questions_dir)

    candidate = get_or_none()
    stats = {
        "profile_pct": 0,
        "applications_total": 0,
        "applications_today": 0,
        "jobs_total": 0,
        "cvs_total": 0,
    }

    if candidate:
        required = corpus.keys_required()
        coverage = fact_repo.coverage_summary(candidate.id, required)
        covered = sum(1 for v in coverage.values() if v)
        stats["profile_pct"] = round(covered / len(required) * 100) if required else 0

        import sqlalchemy as sa
        from ajaa.db.session import get_session
        from ajaa.db.models import Application, Job, CV
        from datetime import date, datetime

        with get_session() as session:
            stats["applications_total"] = session.execute(
                sa.select(sa.func.count()).select_from(Application).where(
                    Application.candidate_id == candidate.id
                )
            ).scalar_one()

            today_start = datetime.combine(date.today(), datetime.min.time())
            stats["applications_today"] = session.execute(
                sa.select(sa.func.count()).select_from(Application).where(
                    Application.candidate_id == candidate.id,
                    Application.created_at >= today_start,
                )
            ).scalar_one()

            stats["applications_submitted"] = session.execute(
                sa.select(sa.func.count()).select_from(Application).where(
                    Application.candidate_id == candidate.id,
                    Application.state == "SUBMITTED",
                )
            ).scalar_one()

            stats["jobs_total"] = session.execute(
                sa.select(sa.func.count()).select_from(Job).where(Job.is_stale == False)
            ).scalar_one()

            stats["cvs_total"] = session.execute(
                sa.select(sa.func.count()).select_from(CV).where(
                    CV.candidate_id == candidate.id,
                    CV.is_active == True,
                )
            ).scalar_one()

    from ajaa.config import get_settings
    settings = get_settings()
    safety_info = {
        "safety_ceiling": settings.policy.safety.max_applications_per_day,
        "operational_target": settings.policy.operational.max_applications_per_day or "UNSET (null)",
        "review_mode": settings.policy.review.default_mode,
        "invariant_i6": "HALT ON SIGHT",
        "invariant_i10": "ROUTE INTERCEPTOR ACTIVE",
        "injection_defense": "LAYER 6 PREFILTER ACTIVE",
    }

    return templates.TemplateResponse(request, "dashboard.html", {
        "candidate": candidate,
        "stats": stats,
        "safety": safety_info,
    })


@app.get("/status", response_class=HTMLResponse)
async def system_status(request: Request):
    from ajaa.bootstrap import run_checks
    result = run_checks()
    return templates.TemplateResponse(request, "status.html", {
        "result": result,
    })


@app.get("/health")
async def health():
    from ajaa.bootstrap import run_checks
    result = run_checks()
    return JSONResponse(
        status_code=200 if result.all_passed else 503,
        content={
            "status": "ok" if result.all_passed else "degraded",
            "checks": [
                {"name": c.name, "ok": c.passed, "detail": c.message}
                for c in result.checks
            ],
        },
    )