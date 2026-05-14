# ruff: noqa: E402
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import sys
from pathlib import Path
from urllib.parse import urlparse

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

import feedparser
from bs4 import BeautifulSoup

from core.config import settings
from core.logger import logger
from ingestion.pipeline import IngestionPipeline, JOB_LOG
from models.schemas import IngestionJobRecord


class NewsIngestor:
    POLL_INTERVAL_SECONDS = 300
    RSS_FEEDS = [
        "https://news.google.com/rss/search?q=coffee+futures&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=coffee+market+today&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=coffee+market+arabica+robusta&hl=en-US&gl=US&ceid=US:en",
        "https://news.google.com/rss/search?q=coffee+market+Reuters&hl=en-US&gl=US&ceid=US:en",
    ]
    MAX_ARTICLES = 25
    COFFEE_KEYWORDS = (
        "coffee",
        "arabica",
        "robusta",
        "espresso",
        "cafe",
        "café",
        "futures",
        "harvest",
        "crop",
        "roaster",
        "bean",
    )
    MARKET_KEYWORDS = (
        "market",
        "markets",
        "futures",
        "price",
        "prices",
        "trade",
        "trading",
        "harvest",
        "crop",
        "supply",
        "demand",
        "export",
        "exports",
        "consumption",
        "yield",
        "yields",
        "deforestation",
        "recovery",
        "shock",
    )
    BLOCKED_TERMS = (
        "market size",
        "industry report",
        "growth report",
        "trade ideas",
        "[2034]",
        "[2026-2034]",
        "statista",
        "indexbox",
        "tradingview",
        "finviz",
    )

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
        records = await asyncio.to_thread(self._fetch_rss_records)
        logger.info("Fetched {} live coffee news records", len(records))
        return records

    async def index_live_news(self, records: list[dict]) -> int:
        if not records:
            return 0
        vector_store = self.ingestion_pipeline.rag_pipeline.retriever.vector_store
        if vector_store.ensure_collection(self.ingestion_pipeline.rag_pipeline.retriever.embedder.dimension()):
            vector_store.delete_by_source("news_rss")
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
        started_at = datetime.now(timezone.utc)
        try:
            records = await self.fetch_live_news()
            raw_path = self.ingestion_pipeline._write_payload(settings.raw_data_dir, "news_rss", records)
            indexed_count = await self.index_live_news(records)
            processed_payload = {
                "source": "news",
                "records_ingested": len(records),
                "documents_indexed": indexed_count,
                "feed_count": len(self.RSS_FEEDS),
                "raw_snapshot": Path(raw_path).name,
            }
            processed_path = self.ingestion_pipeline._write_payload(
                settings.processed_data_dir,
                "news_rss_summary",
                processed_payload,
            )
            record = IngestionJobRecord(
                source="news",
                status="completed",
                records_ingested=len(records),
                documents_indexed=indexed_count,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                detail=f"feeds={len(self.RSS_FEEDS)}; raw={Path(raw_path).name}; processed={Path(processed_path).name}",
                dispatch_mode=dispatch_mode,
            )
        except Exception as exc:
            logger.exception("RSS news ingestion failed: {}", exc)
            record = IngestionJobRecord(
                source="news",
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

    def _fetch_rss_records(self) -> list[dict]:
        records: list[dict] = []
        seen_keys: set[tuple[str, str]] = set()

        for url in self.RSS_FEEDS:
            feed = feedparser.parse(url)
            if getattr(feed, "bozo", 0):
                logger.warning("RSS feed parse warning for {}: {}", url, getattr(feed, "bozo_exception", "unknown"))

            channel = self._feed_channel(feed, url)
            for entry in getattr(feed, "entries", []):
                title = self._clean_text(getattr(entry, "title", ""))
                summary = self._entry_summary(entry)
                if not self._is_relevant_article(title, summary):
                    continue

                link = self._clean_text(getattr(entry, "link", ""))
                key = (link.lower(), title.lower())
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                published_at = self._entry_published_at(entry)
                records.append(
                    {
                        "title": title,
                        "content": self._build_content(title, summary, channel, published_at, link),
                        "record_type": "rss_feed",
                        "raw": {
                            "summary": summary,
                            "feed_url": url,
                            "entry_id": self._clean_text(getattr(entry, "id", "")),
                        },
                        "metadata": {
                            "source": "news_rss",
                            "title": title,
                            "published_at": published_at,
                            "url": link,
                            "channel": channel,
                        },
                    }
                )

        records.sort(
            key=lambda record: self._published_timestamp((record.get("metadata") or {}).get("published_at")),
            reverse=True,
        )
        return records[: self.MAX_ARTICLES]

    def _feed_channel(self, feed, url: str) -> str:
        feed_title = self._clean_text(getattr(getattr(feed, "feed", {}), "get", lambda *_: "")("title"))
        return feed_title or urlparse(url).netloc

    def _entry_summary(self, entry) -> str:
        candidates = [
            getattr(entry, "summary", ""),
            getattr(entry, "description", ""),
        ]

        content_items = getattr(entry, "content", None) or []
        for item in content_items:
            if isinstance(item, dict):
                candidates.append(str(item.get("value") or ""))

        for value in candidates:
            cleaned = self._clean_html(value)
            if cleaned:
                return cleaned
        return ""

    def _entry_published_at(self, entry) -> str:
        for field_name in ("published_parsed", "updated_parsed"):
            parsed_value = getattr(entry, field_name, None)
            if parsed_value:
                return datetime(parsed_value[0], parsed_value[1], parsed_value[2], parsed_value[3], parsed_value[4], parsed_value[5], tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")

        for field_name in ("published", "updated"):
            text_value = self._clean_text(getattr(entry, field_name, ""))
            if text_value:
                return text_value
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _build_content(
        self,
        title: str,
        summary: str,
        channel: str,
        published_at: str,
        link: str,
    ) -> str:
        lines = [title]
        if summary:
            lines.append(summary)
        if published_at:
            lines.append(f"Published: {published_at}")
        if channel:
            lines.append(f"Channel: {channel}")
        if link:
            lines.append(f"Source URL: {link}")
        return "\n".join(lines)

    def _is_relevant_article(self, title: str, summary: str) -> bool:
        lowered = f"{title} {summary}".lower()
        if any(term in lowered for term in self.BLOCKED_TERMS):
            return False
        has_coffee_signal = any(keyword in lowered for keyword in self.COFFEE_KEYWORDS)
        has_market_signal = any(keyword in lowered for keyword in self.MARKET_KEYWORDS)
        return has_coffee_signal and has_market_signal

    def _clean_text(self, value: str | None) -> str:
        return " ".join(str(value or "").split()).strip()

    def _clean_html(self, value: str | None) -> str:
        if not value:
            return ""
        return self._clean_text(BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True))

    def _published_timestamp(self, value) -> float:
        if not value:
            return 0.0
        text = str(value).strip()
        if not text:
            return 0.0
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0


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
