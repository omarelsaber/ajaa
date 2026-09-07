"""
src/ajaa/web/routes/profile.py

Candidate Profile & Fact Ledger management routes (PRD §11 & §28.4).

GET  /profile          — view facts by category, provenance, confidence, and coverage
POST /profile/facts    — add or edit a fact with highest precedence (USER_EXPLICIT)
POST /profile/facts/delete — remove or mark stale a fact
GET  /profile/coverage — JSON coverage summary across core dimensions
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ajaa.candidate.profile import build_profile, compute_profile_version_hash
from ajaa.db.models import Fact
from ajaa.db.repositories import candidate as candidate_repo
from ajaa.db.repositories import fact as fact_repo
from ajaa.db.session import get_session
from ajaa.types import Confidence, FactSource, FactState
import sqlalchemy as sa

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))

_QUESTIONS_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "questions"


def _get_or_create_candidate():
    ctx = candidate_repo.get_or_none()
    if ctx is None:
        ctx = candidate_repo.create(display_name="Me")
    return ctx


def _classify_category(key: str) -> str:
    if key.startswith("personal."):
        return "Personal & Contact"
    elif key.startswith("skill.") or key.startswith("skills."):
        return "Skills & Competencies"
    elif key.startswith("experience."):
        return "Experience & Roles"
    elif key.startswith("education."):
        return "Education & Degrees"
    elif key.startswith("preferences.") or key.startswith("work_authorization."):
        return "Preferences & Authorization"
    return "Other"


@router.get("/profile", response_class=HTMLResponse)
async def view_profile(
    request: Request,
    msg: str | None = None,
    err: str | None = None,
):
    candidate = _get_or_create_candidate()
    profile = build_profile(candidate.id)
    version_hash = profile.profile_version_hash

    from ajaa.interview.corpus import get_corpus
    corpus = get_corpus(_QUESTIONS_DIR)
    required_keys = corpus.keys_required()

    # Load all canonical usable facts
    all_facts = fact_repo.get_all_usable(candidate.id)

    # Group facts by category
    categories: dict[str, list[Fact]] = {
        "Personal & Contact": [],
        "Skills & Competencies": [],
        "Experience & Roles": [],
        "Education & Degrees": [],
        "Preferences & Authorization": [],
        "Other": [],
    }

    for f in all_facts:
        cat = _classify_category(f.fact_key)
        categories[cat].append(f)

    # Calculate coverage
    coverage_map = fact_repo.coverage_summary(candidate.id, required_keys)
    covered_count = sum(1 for v in coverage_map.values() if v)
    coverage_pct = round(covered_count / len(required_keys) * 100) if required_keys else 0

    return templates.TemplateResponse(request, "profile.html", {
        "candidate": candidate,
        "profile": profile,
        "version_hash": version_hash,
        "categories": categories,
        "coverage_pct": coverage_pct,
        "covered_count": covered_count,
        "total_required": len(required_keys),
        "coverage_map": coverage_map,
        "success": msg,
        "error": err,
    })


@router.post("/profile/facts", response_class=HTMLResponse)
async def add_or_update_fact(
    request: Request,
    fact_key: Annotated[str, Form()],
    fact_value: Annotated[str, Form()],
    confidence: Annotated[str, Form()] = "CONFIRMED",
):
    candidate = _get_or_create_candidate()

    key = fact_key.strip()
    val = fact_value.strip()

    if not key or not val:
        return RedirectResponse(url="/profile?err=Fact+key+and+value+are+required.", status_code=303)

    try:
        conf_enum = Confidence[confidence.upper()]
    except KeyError:
        conf_enum = Confidence.CONFIRMED

    # Facts entered or edited by user get Rank 1 (USER_EXPLICIT)
    fact_repo.upsert(
        candidate_id=candidate.id,
        fact_key=key,
        fact_value=val,
        source=FactSource.USER_EXPLICIT,
        confidence=conf_enum,
        state=FactState.KNOWN,
    )

    return RedirectResponse(url=f"/profile?msg=Fact+'{key}'+saved+successfully.", status_code=303)


@router.post("/profile/facts/delete", response_class=HTMLResponse)
async def delete_fact(
    request: Request,
    fact_key: Annotated[str, Form()],
):
    candidate = _get_or_create_candidate()
    key = fact_key.strip()

    with get_session() as session:
        session.execute(
            sa.delete(Fact).where(
                Fact.candidate_id == candidate.id,
                Fact.fact_key == key,
            )
        )
        session.commit()

    return RedirectResponse(url=f"/profile?msg=Fact+'{key}'+removed.", status_code=303)


@router.get("/profile/coverage")
async def profile_coverage_json():
    candidate = _get_or_create_candidate()
    from ajaa.interview.corpus import get_corpus
    corpus = get_corpus(_QUESTIONS_DIR)
    required_keys = corpus.keys_required()

    coverage_map = fact_repo.coverage_summary(candidate.id, required_keys)
    covered_count = sum(1 for v in coverage_map.values() if v)
    coverage_pct = round(covered_count / len(required_keys) * 100) if required_keys else 0

    return JSONResponse(content={
        "candidate_id": candidate.id,
        "coverage_percentage": coverage_pct,
        "covered_count": covered_count,
        "total_required": len(required_keys),
        "details": coverage_map,
    })
