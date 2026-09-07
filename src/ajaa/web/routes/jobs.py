"""
src/ajaa/web/routes/jobs.py

Job discovery, matching, and manual paste routes.

GET  /jobs               — list ranked jobs matched against candidate profile
POST /jobs/scrape        — scrape jobs (e.g. RemoteOK) matching candidate profile
POST /jobs/paste         — manually paste a job listing
POST /jobs/{job_id}/apply — queue application for a job
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ajaa.candidate.profile import build_profile
from ajaa.db.repositories import candidate as candidate_repo
from ajaa.matcher.ranker import load_and_rank
from ajaa.scraper.base import SearchQuery
from ajaa.scraper.normalizer import ingest_jobs
from ajaa.scraper.paste import PasteJobInput, ingest_pasted_job
from ajaa.scraper.remoteok import RemoteOKScraper
from ajaa.scraper.greenhouse import GreenhouseScraper
from ajaa.scraper.lever import LeverScraper
from ajaa.scraper.ashby import AshbyScraper

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


def _get_or_create_candidate():
    ctx = candidate_repo.get_or_none()
    if ctx is None:
        ctx = candidate_repo.create(display_name="Me")
    return ctx


def _get_profile_dict(candidate_id: str) -> dict:
    try:
        profile = build_profile(candidate_id)
        return profile.to_dict()
    except Exception:
        return {}


def _get_applied_job_ids(candidate_id: str) -> set[str]:
    from ajaa.db.session import get_session
    from ajaa.db.models import Application
    import sqlalchemy as sa

    with get_session() as session:
        rows = session.execute(
            sa.select(Application.job_id).where(
                Application.candidate_id == candidate_id
            )
        ).scalars().all()
        return set(rows)


# ── GET /jobs ─────────────────────────────────────────────────────────────────

@router.get("/jobs", response_class=HTMLResponse)
async def list_jobs(
    request: Request,
    msg: str | None = None,
    err: str | None = None,
):
    candidate = _get_or_create_candidate()
    profile_dict = _get_profile_dict(candidate.id)
    applied_ids = _get_applied_job_ids(candidate.id)

    ranked = load_and_rank(
        profile=profile_dict,
        candidate_id=candidate.id,
        threshold=0,  # Show all discovered jobs with their scores
        page=1,
        page_size=100,
    )

    return templates.TemplateResponse(request, "jobs.html", {
        "candidate": candidate,
        "ranked_jobs": ranked,
        "applied_job_ids": applied_ids,
        "success": msg,
        "error": err,
    })


# ── POST /jobs/scrape ─────────────────────────────────────────────────────────

@router.post("/jobs/scrape", response_class=HTMLResponse)
async def scrape_jobs(
    request: Request,
    keyword: Annotated[str, Form()] = "",
    source: Annotated[str, Form()] = "all",
):
    candidate = _get_or_create_candidate()
    profile_dict = _get_profile_dict(candidate.id)

    keywords: list[str] = []
    if keyword.strip():
        keywords = [k.strip() for k in keyword.split(",") if k.strip()]
    else:
        # Auto-detect from candidate target roles and primary language
        target_roles = profile_dict.get("preferences.target_roles", "")
        if target_roles:
            keywords.extend([r.strip() for r in target_roles.split(",") if r.strip()])
        primary_lang = profile_dict.get("skills.primary_language", "")
        if primary_lang and primary_lang not in keywords:
            keywords.append(primary_lang)

    if not keywords:
        keywords = ["ai", "engineer", "python", "developer"]

    query = SearchQuery(keywords=keywords, max_results=30)
    raw_jobs = []

    if source in ("remoteok", "all"):
        try:
            raw_jobs.extend(RemoteOKScraper().scrape(query))
        except Exception:
            pass

    if source in ("greenhouse", "all"):
        try:
            raw_jobs.extend(GreenhouseScraper().scrape(query))
        except Exception:
            pass

    if source in ("lever", "all"):
        try:
            raw_jobs.extend(LeverScraper().scrape(query))
        except Exception:
            pass

    if source in ("ashby", "all"):
        try:
            raw_jobs.extend(AshbyScraper().scrape(query))
        except Exception:
            pass

    if not raw_jobs:
        msg = f"No new jobs found from {source.capitalize()} matching your criteria."
    else:
        results = ingest_jobs(raw_jobs)
        new_count = sum(1 for r in results if not r.was_duplicate)
        dup_count = len(results) - new_count
        msg = f"Discovered {len(raw_jobs)} jobs across {source.upper()} ({new_count} new, {dup_count} existing)."

    return RedirectResponse(url=f"/jobs?msg={msg}", status_code=303)


# ── POST /jobs/paste ──────────────────────────────────────────────────────────

@router.post("/jobs/paste", response_class=HTMLResponse)
async def paste_job(
    request: Request,
    apply_url: Annotated[str, Form()],
    title: Annotated[str, Form()] = "",
    company: Annotated[str, Form()] = "",
    location: Annotated[str, Form()] = "",
    jd_text: Annotated[str, Form()] = "",
    remote_ok: Annotated[str, Form()] = "on",
    salary_raw: Annotated[str, Form()] = "",
):
    if not apply_url.strip():
        return RedirectResponse(url="/jobs?err=URL+is+required+to+paste+a+job", status_code=303)

    inp = PasteJobInput(
        apply_url=apply_url.strip(),
        title=title.strip(),
        company=company.strip(),
        location=location.strip(),
        jd_text=jd_text.strip(),
        remote_ok=bool(remote_ok),
        salary_raw=salary_raw.strip(),
    )
    result = ingest_pasted_job(inp)

    msg = "Pasted job saved and ranked." if not result.was_duplicate else "Job already exists in database (updated)."
    return RedirectResponse(url=f"/jobs?msg={msg}", status_code=303)


# ── POST /jobs/{job_id}/apply & /queue ────────────────────────────────────────

@router.post("/jobs/{job_id}/apply", response_class=HTMLResponse)
@router.post("/jobs/{job_id}/queue", response_class=HTMLResponse)
async def queue_application(
    request: Request,
    job_id: str,
):
    candidate = _get_or_create_candidate()

    from ajaa.db.session import get_session
    from ajaa.db.models import Application, Job
    import sqlalchemy as sa

    with get_session() as session:
        job = session.execute(
            sa.select(Job).where(Job.id == job_id)
        ).scalars().first()

        if job is None:
            return RedirectResponse(url="/jobs?err=Job+not+found", status_code=303)

        existing = session.execute(
            sa.select(Application).where(
                Application.candidate_id == candidate.id,
                Application.job_id == job_id,
            )
        ).scalars().first()

        if existing is None:
            app_record = Application(
                candidate_id=candidate.id,
                job_id=job_id,
                state="QUEUED",
            )
            session.add(app_record)
            session.commit()
            msg = f"Application queued for {job.title or 'Job'} at {job.company or 'Company'}."
        else:
            msg = f"Application already queued (status: {existing.state})."

    return RedirectResponse(url=f"/jobs?msg={msg}", status_code=303)


# ── GET /jobs/{job_id} (Detail & Match Breakdown) ─────────────────────────────

@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def get_job_detail(
    request: Request,
    job_id: str,
):
    candidate = _get_or_create_candidate()
    profile_dict = _get_profile_dict(candidate.id)
    applied_ids = _get_applied_job_ids(candidate.id)

    from ajaa.db.session import get_session
    from ajaa.db.models import Job
    from ajaa.matcher.scorer import score_job
    import sqlalchemy as sa

    with get_session() as session:
        job = session.execute(
            sa.select(Job).where(Job.id == job_id)
        ).scalars().first()

        if job is None:
            return RedirectResponse(url="/jobs?err=Job+not+found", status_code=303)

        job_dict = {
            "id": job.id,
            "title": job.title or "",
            "company": job.company or "",
            "location": job.location or "",
            "remote_ok": job.remote_ok,
            "jd_text": job.jd_text or "",
            "apply_url": job.apply_url,
            "source_connector": job.source_connector,
            "discovered_at": job.discovered_at.strftime("%Y-%m-%d %H:%M") if job.discovered_at else "",
            "quarantined": job.quarantined,
            "quarantine_reason": job.quarantine_reason,
        }

        match_score = score_job(profile_dict, job_dict)
        is_applied = job.id in applied_ids

        return templates.TemplateResponse(request, "job_detail.html", {
            "job": job,
            "job_dict": job_dict,
            "score": match_score,
            "is_applied": is_applied,
            "candidate": candidate,
        })


# ── POST /jobs/{job_id}/skip ──────────────────────────────────────────────────

@router.post("/jobs/{job_id}/skip", response_class=HTMLResponse)
async def skip_job(
    request: Request,
    job_id: str,
    reason: Annotated[str, Form()] = "manual_skip",
):
    from ajaa.db.session import get_session
    from ajaa.db.models import Job
    import sqlalchemy as sa

    with get_session() as session:
        job = session.execute(
            sa.select(Job).where(Job.id == job_id)
        ).scalars().first()

        if job:
            job.is_stale = True
            session.commit()
            title = job.title or "Job"
            msg = f"Skipped '{title}' (reason: {reason})."
        else:
            msg = "Job not found."

    return RedirectResponse(url=f"/jobs?msg={msg}", status_code=303)