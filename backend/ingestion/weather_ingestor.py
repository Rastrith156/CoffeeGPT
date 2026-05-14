# ruff: noqa: E402
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def ensure_local_site_packages() -> None:
    for candidate in (
        BACKEND_ROOT / "venv" / "Lib" / "site-packages",
        BACKEND_ROOT / ".venv" / "Lib" / "site-packages",
    ):
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            return


ensure_local_site_packages()

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.config import settings
from core.logger import logger
from ingestion.pipeline import IngestionPipeline, JOB_LOG
from models.schemas import IngestionJobRecord


class WeatherIngestor:
    POLL_INTERVAL_SECONDS = settings.weather_poll_interval_seconds

    def __init__(self, ingestion_pipeline: IngestionPipeline) -> None:
        self.ingestion_pipeline = ingestion_pipeline

    async def fetch_weather_records(self) -> list[dict]:
        connector = self.ingestion_pipeline.connectors.get("weather")
        if connector is None:
            raise ValueError("Weather connector is not configured.")

        records = await connector.fetch()
        logger.info("Fetched {} structured weather intelligence records", len(records))
        return records

    async def index_weather_records(self, records: list[dict]) -> int:
        if not records:
            return 0

        count = await asyncio.to_thread(self.ingestion_pipeline.rag_pipeline.index_records, records)
        logger.info("Indexed {} weather intelligence chunks into Qdrant", count)
        return count

    def print_terminal_report(self, records: list[dict]) -> None:
        print("\n=== Weather Intelligence ===")
        for index, record in enumerate(records, start=1):
            metadata = record.get("metadata") or {}
            title = str(record.get("title") or "Untitled").strip()
            region = str(metadata.get("region") or "unknown").strip()
            published_at = str(metadata.get("published_at") or "unknown").strip()
            print(f"{index}. {title}")
            print(f"   Region: {region}")
            print(f"   Published: {published_at}")
            print(f"   Summary: {self._summary_text(record)}")
            print()

    def _summary_text(self, record: dict) -> str:
        content = " ".join(str(record.get("content") or "").split()).strip()
        return content or "No summary available."

    async def ingest_once(self, dispatch_mode: str = "scheduled") -> list[IngestionJobRecord]:
        started_at = datetime.now(timezone.utc)
        try:
            records = await self.fetch_weather_records()
            raw_path = self.ingestion_pipeline._write_payload(settings.raw_data_dir, "weather", records)
            indexed_count = await self.index_weather_records(records)
            processed_payload = {
                "source": "weather",
                "records_ingested": len(records),
                "documents_indexed": indexed_count,
                "region_count": len(settings.weather_regions),
                "forecast_days": settings.weather_forecast_days,
                "raw_snapshot": raw_path.name,
            }
            processed_path = self.ingestion_pipeline._write_payload(
                settings.processed_data_dir,
                "weather_summary",
                processed_payload,
            )
            record = IngestionJobRecord(
                source="weather",
                status="completed",
                records_ingested=len(records),
                documents_indexed=indexed_count,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                detail=(
                    f"regions={len(settings.weather_regions)}; forecast_days={settings.weather_forecast_days}; "
                    f"raw={raw_path.name}; processed={processed_path.name}"
                ),
                dispatch_mode=dispatch_mode,
            )
        except Exception as exc:
            logger.exception("Weather ingestion failed: {}", exc)
            record = IngestionJobRecord(
                source="weather",
                status="failed",
                records_ingested=0,
                documents_indexed=0,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                detail=str(exc),
                dispatch_mode=dispatch_mode,
            )
        JOB_LOG.appendleft(record)
        return [record]

    async def run_forever(self, interval_seconds: int = POLL_INTERVAL_SECONDS) -> None:
        while True:
            try:
                jobs = await self.ingest_once(dispatch_mode="scheduled")
                indexed = sum(job.documents_indexed for job in jobs)
                ingested = sum(job.records_ingested for job in jobs)
                logger.info(
                    "Scheduled weather ingestion finished: {} records ingested, {} chunks indexed",
                    ingested,
                    indexed,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Scheduled weather ingestion failed: {}", exc)
            await asyncio.sleep(interval_seconds)


async def main() -> None:
    ingestor = WeatherIngestor(ingestion_pipeline=IngestionPipeline())
    records = await ingestor.fetch_weather_records()
    if not records:
        raise SystemExit("No weather intelligence records were produced.")

    ingestor.print_terminal_report(records)
    indexed_count = await ingestor.index_weather_records(records)
    print(f"Indexed {indexed_count} weather intelligence chunks into Qdrant.")


if __name__ == "__main__":
    asyncio.run(main())
