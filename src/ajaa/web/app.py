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


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    from ajaa.db.repositories.candidate import get_or_none
    from ajaa.db.repositories import fact as fact_repo
    from ajaa.interview.corpus import get_corpus

    questions_dir = Path(__file__).parent.parent.parent.parent / "data" / "questions"
    corpus = get_corpus(questions_dir)

    candidate = get_or_none()
    stats = {"profile_pct": 0, "applications_total": 0, "applications_today": 0}

    if candidate:
        required = corpus.keys_required()
        coverage = fact_repo.coverage_summary(candidate.id, required)
        covered = sum(1 for v in coverage.values() if v)
        stats["profile_pct"] = round(covered / len(required) * 100) if required else 0

        import sqlalchemy as sa
        from ajaa.db.session import get_session
        from ajaa.db.models import Application
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

    return templates.TemplateResponse(request, "dashboard.html", {
        "candidate": candidate,
        "stats": stats,
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