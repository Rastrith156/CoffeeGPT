"""
api/health.py
=============
Task 5 — Health endpoints including deep check.

Routes:
  GET /health          → lightweight liveness check (always fast)
  GET /health/detailed → legacy service health (uses HealthService)
  GET /health/deep     → deep health: pings Qdrant, Redis, Postgres, LMStudio
                         Returns HTTP 503 when status = "unhealthy"
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response
from fastapi.responses import JSONResponse

from core.dependencies import get_health_service
from core.health import deep_health_check
from models.schemas import DetailedHealthResponse, HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness probe — always returns 200 if the process is up."""
    return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc))


@router.get("/health/detailed", response_model=DetailedHealthResponse)
async def health_detailed(
    response: Response,
    health_service=Depends(get_health_service),
) -> DetailedHealthResponse:
    """Legacy aggregate health from HealthService (keeps old API contract)."""
    report = await health_service.collect_health()
    response.status_code = 200 if report.status == "ok" else 207
    return report


@router.get("/health/deep")
async def health_deep(response: Response) -> JSONResponse:
    """
    Task 5 — Deep health check.

    Pings each dependency individually in parallel and returns:
      - per-service status + latency_ms
      - overall rollup: healthy | degraded | unhealthy
      - HTTP 503 when overall = "unhealthy"
    """
    report = await deep_health_check()
    status_code = 503 if report["status"] == "unhealthy" else 200
    return JSONResponse(content=report, status_code=status_code)
