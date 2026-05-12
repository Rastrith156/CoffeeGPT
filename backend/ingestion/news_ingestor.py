from __future__ import annotations

import asyncio
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

    async def fetch_live_news(self) -> list[dict]:
        connector = self.ingestion_pipeline.connectors["news"]
        records = await connector.fetch()
        logger.info("Fetched {} live coffee news records", len(records))
        return records

    async def index_live_news(self, records: list[dict]) -> int:
        if not records:
            return 0
        count = await asyncio.to_thread(self.ingestion_pipeline.rag_pipeline.index_records, records)
        logger.info("Indexed {} live coffee news chunks into Qdrant", count)
        return count

    def print_terminal_report(self, records: list[dict]) -> None:
        print("\n=== Live Coffee News ===")
        for index, record in enumerate(records, start=1):
            metadata = record.get("metadata") or {}
            title = str(record.get("title") or "Untitled").strip()
            summary = self._summary_text(record)
            source = str(metadata.get("channel") or metadata.get("source") or "unknown").strip()
            published_at = str(metadata.get("published_at") or "unknown").strip()
            print(f"{index}. {title}")
            print(f"   Source: {source}")
            print(f"   Published: {published_at}")
            print(f"   Summary: {summary}")
            print()

    def _summary_text(self, record: dict) -> str:
        raw = record.get("raw") or {}
        for key in ("summary", "description"):
            value = str(raw.get(key) or "").strip()
            if value:
                return " ".join(value.split())

        content = str(record.get("content") or "").strip()
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        for line in lines[1:]:
            lowered = line.lower()
            if lowered.startswith("published:") or lowered.startswith("channel:") or lowered.startswith("source url:"):
                continue
            return line
        return lines[0] if lines else "No summary available."

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


async def main() -> None:
    ingestor = NewsIngestor(ingestion_pipeline=IngestionPipeline())
    records = await ingestor.fetch_live_news()
    if not records:
        raise SystemExit("No live coffee news records were fetched.")

    ingestor.print_terminal_report(records)

    indexed_count = await ingestor.index_live_news(records)
    print(f"Indexed {indexed_count} live coffee news chunks into Qdrant.")


if __name__ == "__main__":
    asyncio.run(main())
