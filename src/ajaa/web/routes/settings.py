"""
src/ajaa/web/routes/settings.py

Settings & Configuration routes (PRD §26 & §28.4).

GET  /settings — display Safety Ceilings vs Operational Policy
POST /settings — update operational preferences (bounded by safety ceilings)
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from ajaa.config import get_settings

router = APIRouter()

_templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=str(_templates_dir))


@router.get("/settings", response_class=HTMLResponse)
async def view_settings(
    request: Request,
    msg: str | None = None,
    err: str | None = None,
):
    settings = get_settings()

    safety_ceilings = {
        "max_applications_per_day": settings.policy.safety.max_applications_per_day,
        "max_browser_concurrency": settings.policy.safety.max_browser_concurrency,
        "consent_auto_check": "NEVER (Invariant I6 — Consent Halt)",
        "route_navigation_allowlist": "ENFORCED (Invariant I10 — Apply Host Only)",
        "injection_prefilter": "ACTIVE (Invariant I3 — Quarantine on sight)",
        "captcha_solving": "PROHIBITED (Halt to BLOCKED_BY_SITE)",
    }

    operational_policy = {
        "target_applications_per_day": settings.policy.operational.max_applications_per_day,
        "default_review_mode": settings.policy.review.default_mode,
        "browser_concurrency": settings.policy.operational.browser_concurrency,
    }

    connectors = [
        {"name": "Greenhouse ATS", "type": "Tier 1 Deterministic", "status": "ACTIVE"},
        {"name": "Lever ATS", "type": "Tier 1 Deterministic", "status": "ACTIVE"},
        {"name": "Ashby ATS", "type": "Tier 1 Deterministic", "status": "ACTIVE"},
        {"name": "RemoteOK Job Board", "type": "Remote API Source", "status": "ACTIVE"},
    ]

    return templates.TemplateResponse(request, "settings.html", {
        "safety_ceilings": safety_ceilings,
        "operational_policy": operational_policy,
        "connectors": connectors,
        "success": msg,
        "error": err,
    })


@router.post("/settings", response_class=HTMLResponse)
async def update_settings(
    request: Request,
    target_daily: Annotated[str, Form()] = "",
    review_mode: Annotated[str, Form()] = "always",
):
    settings = get_settings()
    safety_max = settings.policy.safety.max_applications_per_day

    # Parse and validate target daily
    target_val: int | None = None
    if target_daily.strip():
        try:
            target_val = int(target_daily.strip())
            if target_val < 0:
                return RedirectResponse(url="/settings?err=Target+cannot+be+negative.", status_code=303)
            # HARD BOUNDARY: Operational policy can never exceed safety ceiling (PRD §26.1)
            if target_val > safety_max:
                return RedirectResponse(
                    url=f"/settings?err=Operational+target+({target_val})+cannot+exceed+Safety+Ceiling+({safety_max}).",
                    status_code=303,
                )
        except ValueError:
            return RedirectResponse(url="/settings?err=Invalid+number+for+daily+target.", status_code=303)

    # Validate review mode
    allowed_modes = {"always", "first_n_per_connector", "above_score_threshold", "never"}
    mode_normalized = review_mode.lower().strip()
    if mode_normalized not in allowed_modes:
        return RedirectResponse(url="/settings?err=Invalid+review+mode+selected.", status_code=303)

    # In v0.1 settings object in memory
    settings.policy.operational.max_applications_per_day = target_val
    settings.policy.review.default_mode = mode_normalized

    return RedirectResponse(
        url="/settings?msg=Operational+policy+updated+successfully.",
        status_code=303,
    )
