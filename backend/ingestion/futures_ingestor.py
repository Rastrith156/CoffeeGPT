from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
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
from forecasting.market_snapshot import MarketSnapshotGenerator
from ingestion.pipeline import IngestionPipeline, JOB_LOG
from models.schemas import HistoricalFuturesSnapshot, IngestionJobRecord


class FuturesIngestor:
    POLL_INTERVAL_SECONDS = settings.futures_poll_interval_seconds
    HISTORY_DIRECTORY_NAME = "futures_history"

    def __init__(
        self,
        ingestion_pipeline: IngestionPipeline,
        history_root: Path | None = None,
        snapshot_generator: MarketSnapshotGenerator | None = None,
    ) -> None:
        self.ingestion_pipeline = ingestion_pipeline
        self.history_root = history_root or (settings.processed_data_dir / self.HISTORY_DIRECTORY_NAME)
        self.snapshot_generator = snapshot_generator or MarketSnapshotGenerator(
            market_service=self.ingestion_pipeline.market_service,
            weather_service=self.ingestion_pipeline.weather_service,
            news_service=self.ingestion_pipeline.news_service,
        )

    async def fetch_futures_records(self) -> list[dict]:
        connector = self.ingestion_pipeline.connectors.get("futures")
        if connector is None:
            raise ValueError("Futures connector is not configured.")

        records = await connector.fetch()
        logger.info("Fetched {} structured futures intelligence records", len(records))
        return records

    async def index_futures_records(self, records: list[dict]) -> int:
        if not records:
            return 0
        count = await asyncio.to_thread(self.ingestion_pipeline.rag_pipeline.index_records, records)
        logger.info("Indexed {} futures intelligence chunks into Qdrant", count)
        return count

    def print_terminal_report(self, records: list[dict]) -> None:
        print("\n=== Futures Intelligence ===")
        for index, record in enumerate(records, start=1):
            metadata = record.get("metadata") or {}
            title = str(record.get("title") or "Untitled").strip()
            market = str(metadata.get("market") or "unknown").strip()
            published_at = str(metadata.get("published_at") or "unknown").strip()
            print(f"{index}. {title}")
            print(f"   Market: {market}")
            print(f"   Published: {published_at}")
            print(f"   Summary: {self._summary_text(record)}")
            print()

    def _summary_text(self, record: dict) -> str:
        content = " ".join(str(record.get("content") or "").split()).strip()
        return content or "No summary available."

    def extract_historical_snapshots(self, records: list[dict]) -> list[HistoricalFuturesSnapshot]:
        snapshots: list[HistoricalFuturesSnapshot] = []
        for record in records:
            if record.get("record_type") != "futures_snapshot":
                continue

            metadata = record.get("metadata") or {}
            raw = record.get("raw") or {}
            market = str(metadata.get("market") or raw.get("market_key") or "").strip().lower()
            if not market:
                continue

            published_at = metadata.get("published_at") or raw.get("timestamp") or datetime.now(timezone.utc).isoformat()
            snapshot_date = str(
                metadata.get("snapshot_date")
                or raw.get("snapshot_date")
                or str(published_at)[:10]
            )
            snapshots.append(
                HistoricalFuturesSnapshot(
                    market=market,
                    price=self._coerce_float(metadata.get("price") or raw.get("price")),
                    change_percent=self._coerce_float(
                        metadata.get("change_percent") or raw.get("change_percent")
                    ),
                    volatility=self._coerce_float(
                        metadata.get("volatility_pct") or raw.get("volatility_pct")
                    ),
                    timestamp=published_at,
                    snapshot_date=snapshot_date,
                    currency=str(metadata.get("currency") or raw.get("currency") or "") or None,
                    symbol=str(metadata.get("symbol") or raw.get("symbol") or "") or None,
                    contract_month=str(raw.get("contract_month") or "") or None,
                    source_mode=str(raw.get("source_mode") or "") or None,
                )
            )
        return snapshots

    def persist_historical_memory(self, snapshots: list[HistoricalFuturesSnapshot]) -> dict[str, int | list[str]]:
        settings.ensure_directories()
        daily_dir = self.history_root / "daily"
        market_dir = self.history_root / "markets"
        daily_dir.mkdir(parents=True, exist_ok=True)
        market_dir.mkdir(parents=True, exist_ok=True)

        existing_market_dates: dict[str, set[str]] = {}
        additions_by_date: dict[str, list[dict]] = {}
        appended_market_files: set[str] = set()
        persisted = 0
        skipped = 0

        ordered_snapshots = sorted(
            snapshots,
            key=lambda item: (item.snapshot_date or item.timestamp.date().isoformat(), item.market),
        )
        for snapshot in ordered_snapshots:
            market_key = snapshot.market.lower()
            snapshot_date = snapshot.snapshot_date or snapshot.timestamp.date().isoformat()
            market_path = market_dir / f"{market_key}.jsonl"
            seen_dates = existing_market_dates.setdefault(
                market_key,
                self._existing_snapshot_dates(market_path),
            )
            if snapshot_date in seen_dates:
                skipped += 1
                continue

            payload = snapshot.model_dump(mode="json", exclude_none=True)
            with market_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload) + "\n")

            seen_dates.add(snapshot_date)
            additions_by_date.setdefault(snapshot_date, []).append(payload)
            appended_market_files.add(market_path.name)
            persisted += 1

        updated_daily_files: list[str] = []
        for snapshot_date, entries in sorted(additions_by_date.items()):
            daily_path = daily_dir / f"{snapshot_date}.json"
            existing_daily_entries = self._load_daily_entries(daily_path)
            existing_markets = {
                str(item.get("market") or "").strip().lower()
                for item in existing_daily_entries
            }
            merged_entries = list(existing_daily_entries)
            for entry in entries:
                market_key = str(entry.get("market") or "").strip().lower()
                if market_key in existing_markets:
                    continue
                existing_markets.add(market_key)
                merged_entries.append(entry)

            merged_entries.sort(key=lambda item: str(item.get("market") or ""))
            daily_path.write_text(json.dumps(merged_entries, indent=2), encoding="utf-8")
            updated_daily_files.append(daily_path.name)

        logger.info(
            "Historical futures memory updated with {} new daily snapshots ({} skipped as duplicates)",
            persisted,
            skipped,
        )
        return {
            "snapshots_detected": len(snapshots),
            "snapshots_persisted": persisted,
            "snapshots_skipped": skipped,
            "daily_files_updated": updated_daily_files,
            "market_files_updated": sorted(appended_market_files),
        }

    async def build_predictive_snapshot(self, records: list[dict]):
        snapshot = await self.snapshot_generator.generate_from_records(records)
        derived_records = self.snapshot_generator.build_retrieval_records(snapshot)
        return snapshot, derived_records

    def _existing_snapshot_dates(self, market_path: Path) -> set[str]:
        if not market_path.exists():
            return set()

        dates: set[str] = set()
        try:
            for line in market_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                snapshot_date = str(payload.get("snapshot_date") or "")[:10]
                if snapshot_date:
                    dates.add(snapshot_date)
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return set()
        return dates

    def _load_daily_entries(self, daily_path: Path) -> list[dict]:
        if not daily_path.exists():
            return []
        try:
            payload = json.loads(daily_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return payload if isinstance(payload, list) else []

    def _coerce_float(self, value) -> float:
        try:
            return float(str(value).replace(",", "").strip() or 0.0)
        except (TypeError, ValueError):
            return 0.0

    async def ingest_once(self, dispatch_mode: str = "scheduled") -> list[IngestionJobRecord]:
        started_at = datetime.now(timezone.utc)
        try:
            records = await self.fetch_futures_records()
            historical_snapshots = self.extract_historical_snapshots(records)
            historical_memory = await asyncio.to_thread(
                self.persist_historical_memory,
                historical_snapshots,
            )
            predictive_snapshot, derived_records = await self.build_predictive_snapshot(records)
            if predictive_snapshot.alert_feed is not None:
                alert_memory = await asyncio.to_thread(
                    self.snapshot_generator.alert_engine.persist_alert_memory,
                    predictive_snapshot.alert_feed,
                )
            else:
                alert_memory = {
                    "alerts_detected": 0,
                    "alerts_persisted": 0,
                    "alerts_skipped": 0,
                    "daily_files_updated": [],
                    "market_files_updated": [],
                }
            records_to_index = [*records, *derived_records]
            raw_path = self.ingestion_pipeline._write_payload(settings.raw_data_dir, "futures", records)
            indexed_count = await self.index_futures_records(records_to_index)
            processed_payload = {
                "source": "futures",
                "records_ingested": len(records),
                "derived_records_generated": len(derived_records),
                "documents_indexed": indexed_count,
                "raw_snapshot": raw_path.name,
                "historical_memory": historical_memory,
                "alert_memory": alert_memory,
                "market_snapshot": predictive_snapshot.model_dump(mode="json"),
            }
            processed_path = self.ingestion_pipeline._write_payload(
                settings.processed_data_dir,
                "futures_summary",
                processed_payload,
            )
            record = IngestionJobRecord(
                source="futures",
                status="completed",
                records_ingested=len(records),
                documents_indexed=indexed_count,
                started_at=started_at,
                finished_at=datetime.now(timezone.utc),
                detail=(
                    f"raw={raw_path.name}; processed={processed_path.name}; "
                    f"history_persisted={historical_memory['snapshots_persisted']}; "
                    f"alerts_persisted={alert_memory['alerts_persisted']}; "
                    f"derived_records={len(derived_records)}"
                ),
                dispatch_mode=dispatch_mode,
            )
        except Exception as exc:
            logger.exception("Futures ingestion failed: {}", exc)
            record = IngestionJobRecord(
                source="futures",
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
                    "Scheduled futures ingestion finished: {} records ingested, {} chunks indexed",
                    ingested,
                    indexed,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Scheduled futures ingestion failed: {}", exc)
            await asyncio.sleep(interval_seconds)

async def main() -> None:
    ingestor = FuturesIngestor(ingestion_pipeline=IngestionPipeline())
    records = await ingestor.fetch_futures_records()
    if not records:
        raise SystemExit("No futures intelligence records were produced.")

    ingestor.print_terminal_report(records)
    history_summary = await asyncio.to_thread(
        ingestor.persist_historical_memory,
        ingestor.extract_historical_snapshots(records),
    )
    predictive_snapshot, derived_records = await ingestor.build_predictive_snapshot(records)
    alert_summary = {"alerts_persisted": 0}
    if predictive_snapshot.alert_feed is not None:
        alert_summary = await asyncio.to_thread(
            ingestor.snapshot_generator.alert_engine.persist_alert_memory,
            predictive_snapshot.alert_feed,
        )
    indexed_count = await ingestor.index_futures_records([*records, *derived_records])
    print(f"Historical futures snapshots persisted: {history_summary['snapshots_persisted']}")
    print(predictive_snapshot.headline)
    if predictive_snapshot.risk_assessment is not None:
        print(predictive_snapshot.risk_assessment.explanation)
    print(f"Decision-support alerts persisted: {alert_summary['alerts_persisted']}")
    print(f"Indexed {indexed_count} futures intelligence chunks into Qdrant.")


if __name__ == "__main__":
    asyncio.run(main())
