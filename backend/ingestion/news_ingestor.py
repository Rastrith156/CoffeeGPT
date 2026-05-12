from __future__ import annotations

import asyncio

from core.logger import logger
from ingestion.pipeline import IngestionPipeline
from models.schemas import IngestionJobRecord


class NewsIngestor:
    POLL_INTERVAL_SECONDS = 300

    def __init__(self, ingestion_pipeline: IngestionPipeline) -> None:
        self.ingestion_pipeline = ingestion_pipeline
        self._bootstrap_seeded = False
        self._seed_lock = asyncio.Lock()

    def _bootstrap_article(self) -> dict:
        return {
            "title": "Brazil coffee production may decline due to heavy rainfall",
            "content": (
                "Brazil coffee production may decline due to heavy rainfall in key growing regions. "
                "Flooded fields and delayed harvest activity could tighten near-term supply and put "
                "upward pressure on coffee prices."
            ),
            "record_type": "bootstrap_news_article",
            "raw": {
                "summary": "Bootstrap coffee market article used to validate the first end-to-end RAG flow.",
            },
            "metadata": {
                "source": "bootstrap_news",
                "title": "Brazil coffee production may decline due to heavy rainfall",
                "published_at": "2026-05-12",
                "url": "https://example.com/bootstrap/brazil-rainfall",
                "channel": "Bootstrap Seed",
            },
        }

    async def seed_bootstrap_article(self) -> int:
        async with self._seed_lock:
            if self._bootstrap_seeded:
                return 0

            count = await asyncio.to_thread(
                self.ingestion_pipeline.rag_pipeline.index_records,
                [self._bootstrap_article()],
            )
            if count > 0:
                self._bootstrap_seeded = True
            logger.info("Seeded bootstrap coffee article into Qdrant with {} chunks", count)
            return count

    async def ingest_once(self, dispatch_mode: str = "scheduled") -> list[IngestionJobRecord]:
        return await self.ingestion_pipeline.run(source="news", dispatch_mode=dispatch_mode)

    async def run_forever(self, interval_seconds: int = POLL_INTERVAL_SECONDS) -> None:
        await self.seed_bootstrap_article()
        while True:
            try:
                jobs = await self.ingest_once(dispatch_mode="scheduled")
                indexed = sum(job.documents_indexed for job in jobs)
                ingested = sum(job.records_ingested for job in jobs)
                logger.info(
                    "Scheduled news ingestion finished: {} records ingested, {} chunks indexed",
                    ingested,
                    indexed,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Scheduled news ingestion failed: {}", exc)
            await asyncio.sleep(interval_seconds)
