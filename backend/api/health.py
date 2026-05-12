from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response

from core.dependencies import get_health_service
from models.schemas import DetailedHealthResponse, HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc))


@router.get("/health/detailed", response_model=DetailedHealthResponse)
async def health_detailed(
    response: Response,
    health_service=Depends(get_health_service),
) -> DetailedHealthResponse:
    report = await health_service.collect_health()
    response.status_code = 200 if report.status == "ok" else 207
    return report
