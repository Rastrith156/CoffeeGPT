from __future__ import annotations

import asyncio

from core.celery_app import celery_app
from core.runtime import build_container


@celery_app.task(name="ingestion.run")
def run_ingestion_job(source: str = "all", force: bool = False):
    container = build_container()
    jobs = asyncio.run(
        container.ingestion_pipeline.run(
            source=source,
            force=force,
            dispatch_mode="celery",
        )
    )
    return [job.model_dump(mode="json") for job in jobs]
