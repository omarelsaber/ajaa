"""
src/ajaa/web/routes/control.py

FastAPI routes for runtime system controls & emergency panic switch (PRD §26.5).
"""
from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from ajaa.orchestration.control import SystemController

router = APIRouter(prefix="/control", tags=["control"])


@router.get("/status")
async def get_status():
    """Return JSON status of the execution engine."""
    ctrl = SystemController.get()
    status = ctrl.get_status()
    return JSONResponse({
        "status": status.status.value,
        "is_paused": status.is_paused,
        "panic_tripped": status.panic_tripped,
        "active_workers": status.active_workers,
        "message": status.message,
    })


@router.post("/pause")
async def pause_system(request: Request):
    """Pause background application processing."""
    ctrl = SystemController.get()
    ctrl.pause()
    referer = request.headers.get("referer", "/")
    sep = "&" if "?" in referer else "?"
    return RedirectResponse(url=f"{referer}{sep}msg=System+execution+paused.+Current+step+will+finish.", status_code=303)


@router.post("/resume")
async def resume_system(request: Request):
    """Resume background application processing."""
    ctrl = SystemController.get()
    ctrl.resume()
    referer = request.headers.get("referer", "/")
    sep = "&" if "?" in referer else "?"
    return RedirectResponse(url=f"{referer}{sep}msg=System+execution+resumed.", status_code=303)


@router.post("/panic")
async def panic_system(request: Request):
    """Emergency kill switch (PRD §26.5): immediate abort of all automation."""
    ctrl = SystemController.get()
    ctrl.panic()
    referer = request.headers.get("referer", "/")
    sep = "&" if "?" in referer else "?"
    return RedirectResponse(url=f"{referer}{sep}err=EMERGENCY+PANIC+ENGAGED.+All+active+browser+sessions+terminated.", status_code=303)
