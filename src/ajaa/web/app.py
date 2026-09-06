"""
src/ajaa/web/app.py

FastAPI application skeleton.
Phase 0: one health-check route only.
Real routes added in Phase 1+.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(
    title="AJAA",
    description="Autonomous Job Application Agent",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url=None,
)


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "version": "0.1.0"})