from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from forecasting.alert_engine import AlertEngine
from forecasting.correlation_engine import CorrelationEngine
from forecasting.risk_engine import RiskEngine
from models.schemas import (
    AlertFeedResponse,
    HistoricalFuturesSnapshot,
    MarketRiskAssessmentResponse,
    MarketCorrelationInsight,
    MarketCorrelationResponse,
    MarketIntelligenceSnapshotResponse,
    MarketSnapshotSignal,
    NewsCategory,
)
from services.market_service import MarketService
from services.news_service import NewsService
from services.weather_service import WeatherService


class MarketSnapshotGenerator:
    def __init__(
        self,
        *,
        market_service: MarketService,
        weather_service: WeatherService,
        news_service: NewsService,
        correlation_engine: CorrelationEngine | None = None,
        risk_engine: RiskEngine | None = None,
        alert_engine: AlertEngine | None = None,
    ) -> None:
        self.market_service = market_service
        self.weather_service = weather_service
        self.news_service = news_service
        self.correlation_engine = correlation_engine or CorrelationEngine()
        self.risk_engine = risk_engine or RiskEngine()
        self.alert_engine = alert_engine or AlertEngine()

    async def generate(self) -> MarketIntelligenceSnapshotResponse:
        futures = await self.market_service.get_futures()
        news_feed = await self.news_service.get_latest(limit=8, category=NewsCategory.prices.value)
        snapshots = [self._snapshot_from_contract(contract) for contract in futures.contracts]
        return await self._build_snapshot(
            futures_snapshots=snapshots,
            futures_service_mode=futures.service_mode,
            news_articles=list(news_feed.articles),
        )

    async def generate_from_records(self, records: list[dict]) -> MarketIntelligenceSnapshotResponse:
        snapshots = self._snapshots_from_records(records)
        if not snapshots:
            return await self.generate()

        news_feed = await self.news_service.get_latest(limit=8, category=NewsCategory.prices.value)
        return await self._build_snapshot(
            futures_snapshots=snapshots,
            futures_service_mode=self._records_service_mode(records),
            news_articles=list(news_feed.articles),
        )

    def build_retrieval_records(self, snapshot: MarketIntelligenceSnapshotResponse) -> list[dict]:
        snapshot_date = snapshot.generated_at.date().isoformat()
        published_at = snapshot.generated_at.isoformat()
        records = [
            {
                "title": "Daily coffee market intelligence snapshot",
                "content": "\n".join(
                    (
                        snapshot.headline,
                        snapshot.summary,
                        f"Cross-market: {snapshot.cross_market_summary}",
                        f"Outlook: {snapshot.outlook}",
                    )
                ),
                "record_type": "market_intelligence_snapshot",
                "raw": snapshot.model_dump(mode="json"),
                "metadata": {
                    "source": "forecasting",
                    "title": "Daily coffee market intelligence snapshot",
                    "document_id": f"market_snapshot::global::{snapshot_date}",
                    "market": "global",
                    "published_at": published_at,
                    "snapshot_date": snapshot_date,
                    "sentiment": snapshot.sentiment,
                },
            }
        ]

        for insight in snapshot.correlations:
            driver_labels = ", ".join(
                f"{driver.driver_type}:{driver.impact}:{driver.signal}" for driver in insight.drivers[:3]
            )
            records.append(
                {
                    "title": f"{insight.market.capitalize()} causal intelligence",
                    "content": "\n".join(
                        (
                            insight.causal_summary,
                            f"Drivers: {driver_labels or 'none'}",
                            f"Direction: {insight.direction} with confidence {insight.confidence:.2f}",
                        )
                    ),
                    "record_type": "market_correlation_intelligence",
                    "raw": insight.model_dump(mode="json"),
                    "metadata": {
                        "source": "forecasting",
                        "title": f"{insight.market.capitalize()} causal intelligence",
                        "document_id": f"market_correlation::{insight.market}::{snapshot_date}",
                        "market": insight.market,
                        "published_at": published_at,
                        "snapshot_date": snapshot_date,
                        "direction": insight.direction,
                    },
                }
            )

        records.extend(
            self.alert_engine.build_retrieval_records(
                risk_assessment=snapshot.risk_assessment,
                alert_feed=snapshot.alert_feed,
            )
        )
        return records

    async def correlation_report(self) -> MarketCorrelationResponse:
        futures = await self.market_service.get_futures()
        news_feed = await self.news_service.get_latest(limit=8, category=NewsCategory.prices.value)
        futures_snapshots = [self._snapshot_from_contract(contract) for contract in futures.contracts]
        weather_context = await self._load_weather_context({snapshot.market for snapshot in futures_snapshots})
        return self.correlation_engine.analyze(
            futures_snapshots=futures_snapshots,
            weather_context=weather_context,
            news_articles=list(news_feed.articles),
            generated_at=datetime.now(timezone.utc),
        )

    async def risk_report(self) -> MarketRiskAssessmentResponse | None:
        snapshot = await self.generate()
        return snapshot.risk_assessment

    async def alert_report(self) -> AlertFeedResponse | None:
        snapshot = await self.generate()
        return snapshot.alert_feed

    async def _build_snapshot(
        self,
        *,
        futures_snapshots: list[HistoricalFuturesSnapshot],
        futures_service_mode: str,
        news_articles,
    ) -> MarketIntelligenceSnapshotResponse:
        generated_at = datetime.now(timezone.utc)
        weather_context = await self._load_weather_context({snapshot.market for snapshot in futures_snapshots})
        correlation_report = self.correlation_engine.analyze(
            futures_snapshots=futures_snapshots,
            weather_context=weather_context,
            news_articles=list(news_articles),
            generated_at=generated_at,
        )
        risk_assessment = self.risk_engine.analyze(
            futures_snapshots=futures_snapshots,
            weather_context=weather_context,
            news_articles=list(news_articles),
            correlations=correlation_report,
            generated_at=generated_at,
        )
        alert_feed = self.alert_engine.generate(
            futures_snapshots=futures_snapshots,
            weather_context=weather_context,
            news_articles=list(news_articles),
            risk_assessment=risk_assessment,
            correlations=correlation_report,
            generated_at=generated_at,
        )
        lead_insight = max(
            correlation_report.insights,
            key=lambda item: (abs(item.change_percent), item.confidence),
            default=None,
        )
        market_narratives = {
            insight.market: insight.causal_summary
            for insight in correlation_report.insights
        }
        key_signals = [self._signal_from_insight(insight) for insight in correlation_report.insights]
        headline = self._headline(lead_insight, correlation_report.cross_market_summary)
        summary = self._summary(correlation_report.insights)
        outlook = self._outlook(correlation_report.insights)
        sentiment = self._sentiment(correlation_report.insights)

        return MarketIntelligenceSnapshotResponse(
            generated_at=generated_at,
            headline=headline,
            summary=summary,
            sentiment=sentiment,
            outlook=outlook,
            cross_market_summary=correlation_report.cross_market_summary,
            market_narratives=market_narratives,
            key_signals=key_signals,
            correlations=correlation_report.insights,
            risk_assessment=risk_assessment,
            alert_feed=alert_feed,
            service_mode=f"daily_market_snapshot::{futures_service_mode}",
        )

    async def _load_weather_context(self, markets: set[str]) -> dict[str, list]:
        from typing import Any, Awaitable
        tasks: list[tuple[str, str, Awaitable[Any]]] = []
        for market in sorted(markets):
            for region in self.correlation_engine.MARKET_REGIONS.get(market.lower(), ()):
                tasks.append((market.lower(), region, self.weather_service.get_snapshot(region=region, days=3)))

        results = await asyncio.gather(
            *[task for _, _, task in tasks],
            return_exceptions=True,
        )
        weather_context: dict[str, list] = {market.lower(): [] for market in markets}
        for (market, _region, _task), result in zip(tasks, results, strict=False):
            if isinstance(result, Exception):
                continue
            weather_context.setdefault(market, []).append(result)
        return weather_context

    def _snapshot_from_contract(self, contract) -> HistoricalFuturesSnapshot:
        timestamp = contract.timestamp or datetime.now(timezone.utc)
        return HistoricalFuturesSnapshot(
            market=contract.market_key,
            price=contract.price,
            change_percent=contract.change_percent,
            volatility=contract.volatility_pct,
            timestamp=timestamp,
            snapshot_date=timestamp.date().isoformat(),
            currency=contract.currency,
            symbol=contract.symbol,
            contract_month=contract.contract_month,
            source_mode=contract.source_mode,
        )

    def _snapshots_from_records(self, records: list[dict]) -> list[HistoricalFuturesSnapshot]:
        snapshots: list[HistoricalFuturesSnapshot] = []
        for record in records:
            if record.get("record_type") != "futures_snapshot":
                continue
            metadata = record.get("metadata") or {}
            raw = record.get("raw") or {}
            market = str(metadata.get("market") or raw.get("market_key") or "").strip().lower()
            if not market:
                continue
            timestamp = metadata.get("published_at") or raw.get("timestamp") or datetime.now(timezone.utc).isoformat()
            if isinstance(timestamp, str):
                parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            else:
                parsed_timestamp = timestamp if isinstance(timestamp, datetime) else datetime.now(timezone.utc)
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
                    timestamp=parsed_timestamp,
                    snapshot_date=str(
                        metadata.get("snapshot_date")
                        or raw.get("snapshot_date")
                        or str(timestamp)[:10]
                    ),
                    currency=str(metadata.get("currency") or raw.get("currency") or "") or None,
                    symbol=str(metadata.get("symbol") or raw.get("symbol") or "") or None,
                    contract_month=str(raw.get("contract_month") or "") or None,
                    source_mode=str(raw.get("source_mode") or "") or None,
                )
            )
        return snapshots

    def _records_service_mode(self, records: list[dict]) -> str:
        for record in records:
            raw = record.get("raw") or {}
            metadata = record.get("metadata") or {}
            service_mode = raw.get("service_mode") or metadata.get("service_mode")
            if service_mode:
                return str(service_mode)
        return "ingested_futures_records"

    def _signal_from_insight(self, insight: MarketCorrelationInsight) -> MarketSnapshotSignal:
        primary_driver = max(insight.drivers, key=lambda item: item.confidence, default=None)
        return MarketSnapshotSignal(
            market=insight.market,
            price=insight.price,
            change_percent=insight.change_percent,
            volatility=insight.volatility,
            direction=insight.direction,
            primary_driver=primary_driver.signal if primary_driver is not None else "signal mix remains tentative",
            confidence=insight.confidence,
        )

    def _headline(self, lead_insight: MarketCorrelationInsight | None, cross_market_summary: str) -> str:
        if lead_insight is None:
            return "Coffee futures intelligence snapshot is unavailable."
        primary_driver = max(lead_insight.drivers, key=lambda item: item.confidence, default=None)
        driver_text = (
            primary_driver.signal.lower()
            if primary_driver is not None
            else cross_market_summary.lower()
        )
        move_verb = "rose" if lead_insight.change_percent > 0 else "fell" if lead_insight.change_percent < 0 else "held steady"
        return (
            f"{lead_insight.market.capitalize()} futures {move_verb} {abs(lead_insight.change_percent):.2f}% "
            f"as {driver_text}."
        )

    def _summary(self, insights: list[MarketCorrelationInsight]) -> str:
        if not insights:
            return "No market intelligence summary could be generated."
        ordered = sorted(insights, key=lambda item: (abs(item.change_percent), item.confidence), reverse=True)
        sentences = [insight.causal_summary for insight in ordered[:2]]
        return " ".join(sentences)

    def _outlook(self, insights: list[MarketCorrelationInsight]) -> str:
        bullish = sum(1 for insight in insights if insight.direction == "bullish")
        bearish = sum(1 for insight in insights if insight.direction == "bearish")
        if bullish and not bearish:
            return (
                "Short-term tone remains constructive while weather risk and supply-side headlines continue to "
                "support the coffee complex."
            )
        if bearish and not bullish:
            return (
                "Short-term tone remains defensive while the signal set leans toward easier supply or softer buying "
                "conviction."
            )
        return (
            "Short-term tone is mixed, so the next confirmation points are Brazil and Vietnam weather updates plus "
            "fresh export-flow headlines."
        )

    def _sentiment(self, insights: list[MarketCorrelationInsight]) -> str:
        if not insights:
            return "unavailable"
        total_score = 0.0
        for insight in insights:
            if insight.direction == "bullish":
                total_score += insight.confidence
            elif insight.direction == "bearish":
                total_score -= insight.confidence
        if total_score >= 0.45:
            return "constructive"
        if total_score <= -0.45:
            return "defensive"
        return "mixed"

    def _coerce_float(self, value) -> float:
        try:
            return float(str(value).replace(",", "").strip() or 0.0)
        except (TypeError, ValueError):
            return 0.0
