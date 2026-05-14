from __future__ import annotations

import asyncio
import json
from collections import deque
from datetime import datetime, timezone

from core.config import settings
from core.logger import logger
from ingestion.connectors import build_connectors
from models.schemas import (
    IngestionJobRecord,
    IngestionSource,
    IngestionStatusResponse,
    SourceCatalogResponse,
)
from rag.pipeline import RAGPipeline
from services.market_service import MarketService
from services.news_service import NewsService
from services.weather_service import WeatherService

JOB_LOG: deque[IngestionJobRecord] = deque(maxlen=100)


class IngestionPipeline:
    def __init__(
        self,
        market_service: MarketService | None = None,
        weather_service: WeatherService | None = None,
        news_service: NewsService | None = None,
        rag_pipeline: RAGPipeline | None = None,
    ) -> None:
        self.market_service = market_service or MarketService()
        self.weather_service = weather_service or WeatherService()
        self.news_service = news_service or NewsService()
        self.rag_pipeline = rag_pipeline or RAGPipeline()
        self.connectors = build_connectors(
            market_service=self.market_service,
            weather_service=self.weather_service,
            news_service=self.news_service,
            regions=settings.weather_regions,
        )

    async def run(
        self,
        source: str = IngestionSource.all.value,
        force: bool = False,
        dispatch_mode: str = "background",
    ) -> list[IngestionJobRecord]:
        _ = force
        requested_source = source.value if isinstance(source, IngestionSource) else source
        sources = list(self.connectors.keys()) if requested_source == IngestionSource.all.value else [requested_source]
        results: list[IngestionJobRecord] = []

        for source_name in sources:
            if source_name == IngestionSource.futures.value:
                from ingestion.futures_ingestor import FuturesIngestor

                futures_ingestor = FuturesIngestor(ingestion_pipeline=self)
                futures_jobs = await futures_ingestor.ingest_once(dispatch_mode=dispatch_mode)
                results.extend(futures_jobs)
                continue

            started_at = datetime.now(timezone.utc)
            connector = self.connectors.get(source_name)
            if connector is None:
                record = IngestionJobRecord(
                    source=source_name,
                    status="failed",
                    records_ingested=0,
                    documents_indexed=0,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    detail="Unknown source",
                    dispatch_mode=dispatch_mode,
                )
                JOB_LOG.appendleft(record)
                results.append(record)
                continue

            try:
                logger.info("Running ingestion connector {}", source_name)
                records = await connector.fetch()
                raw_path = self._write_payload(settings.raw_data_dir, source_name, records)
                indexed_count = await asyncio.to_thread(self.rag_pipeline.index_records, records)
                processed_payload = {
                    "source": source_name,
                    "records_ingested": len(records),
                    "documents_indexed": indexed_count,
                    "raw_snapshot": raw_path.name,
                }
                processed_path = self._write_payload(
                    settings.processed_data_dir,
                    f"{source_name}_summary",
                    processed_payload,
                )
                record = IngestionJobRecord(
                    source=source_name,
                    status="completed",
                    records_ingested=len(records),
                    documents_indexed=indexed_count,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    detail=f"raw={raw_path.name}; processed={processed_path.name}",
                    dispatch_mode=dispatch_mode,
                )
            except Exception as exc:
                logger.exception("Ingestion failed for {}", source_name)
                record = IngestionJobRecord(
                    source=source_name,
                    status="failed",
                    records_ingested=0,
                    documents_indexed=0,
                    started_at=started_at,
                    finished_at=datetime.now(timezone.utc),
                    detail=str(exc),
                    dispatch_mode=dispatch_mode,
                )

            JOB_LOG.appendleft(record)
            results.append(record)

        return results

    async def get_status(self) -> IngestionStatusResponse:
        return IngestionStatusResponse(
            total_jobs=len(JOB_LOG),
            recent_jobs=list(JOB_LOG),
            last_updated=datetime.now(timezone.utc),
        )

    def list_sources(self) -> SourceCatalogResponse:
        descriptors = [connector.descriptor() for connector in self.connectors.values()]
        return SourceCatalogResponse(sources=descriptors, total=len(descriptors))

    def _write_payload(self, directory, prefix: str, payload) -> str:
        settings.ensure_directories()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        path = directory / f"{prefix}_{timestamp}.json"
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path
