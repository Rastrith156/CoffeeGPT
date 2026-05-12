from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends

from core.config import settings
from core.dependencies import get_ingestion_pipeline
from ingestion.tasks import run_ingestion_job
from models.schemas import (
    IngestionRunResponse,
    IngestionStatusResponse,
    IngestionTriggerRequest,
    SourceCatalogResponse,
)

router = APIRouter()


@router.post("/ingest/trigger", response_model=IngestionRunResponse)
async def trigger_ingestion(
    request: IngestionTriggerRequest,
    background_tasks: BackgroundTasks,
    pipeline=Depends(get_ingestion_pipeline),
) -> IngestionRunResponse:
    source_value = request.source.value
    if settings.use_celery_for_ingestion:
        task = run_ingestion_job.delay(source=source_value, force=request.force_refresh)
        return IngestionRunResponse(
            status="queued",
            source=source_value,
            dispatch_mode="celery",
            job_id=task.id,
            message="Ingestion was queued in Celery.",
        )

    background_tasks.add_task(
        pipeline.run,
        source=source_value,
        force=request.force_refresh,
        dispatch_mode="background",
    )
    return IngestionRunResponse(
        status="queued",
        source=source_value,
        dispatch_mode="background",
        message="Ingestion was scheduled in the FastAPI background task runner.",
    )


@router.get("/ingest/status", response_model=IngestionStatusResponse)
async def get_ingestion_status(pipeline=Depends(get_ingestion_pipeline)) -> IngestionStatusResponse:
    return await pipeline.get_status()


@router.get("/ingest/sources", response_model=SourceCatalogResponse)
async def list_sources(pipeline=Depends(get_ingestion_pipeline)) -> SourceCatalogResponse:
    return pipeline.list_sources()
