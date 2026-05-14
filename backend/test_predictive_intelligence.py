# ruff: noqa: E402
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

backend_root = Path(__file__).resolve().parent


def ensure_local_site_packages() -> None:
    for candidate in (
        backend_root / "venv" / "Lib" / "site-packages",
        backend_root / ".venv" / "Lib" / "site-packages",
    ):
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            return


ensure_local_site_packages()

if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from forecasting.correlation_engine import CorrelationEngine
from forecasting.alert_engine import AlertEngine
from forecasting.market_snapshot import MarketSnapshotGenerator
from forecasting.risk_engine import RiskEngine
from ingestion.futures_ingestor import FuturesIngestor
from models.schemas import (
    HistoricalFuturesSnapshot,
    MarketFuturesResponse,
    NewsArticle,
    NewsFeedResponse,
    WeatherCurrentResponse,
    WeatherForecastPoint,
    WeatherForecastResponse,
    FuturesContract,
)
from services.weather_service import WeatherRegionProfile, WeatherSnapshot


def build_weather_snapshot(
    region: str,
    *,
    rainfall_mm: float,
    probability_pct: float,
    humidity_pct: float,
    temp_c: float = 21.0,
) -> WeatherSnapshot:
    now = datetime(2026, 5, 14, 6, 0, tzinfo=timezone.utc)
    profile = WeatherRegionProfile(name=region, country="test", lat=0.0, lon=0.0)
    current = WeatherCurrentResponse(
        region=region,
        lat=0.0,
        lon=0.0,
        temperature_c=temp_c,
        humidity_pct=humidity_pct,
        rainfall_mm=rainfall_mm / 3.0,
        wind_speed_ms=3.0,
        description="rain bands",
        timestamp=now,
        service_mode="test_weather",
    )
    forecast = WeatherForecastResponse(
        region=region,
        days=3,
        forecast=[
            WeatherForecastPoint(
                day=day_index + 1,
                date=(now + timedelta(days=day_index + 1)).date().isoformat(),
                temp_c=temp_c - 0.5,
                humidity_pct=humidity_pct,
                rainfall_mm=round(rainfall_mm / 3.0, 2),
                wind_speed_ms=3.2,
                precipitation_probability_pct=probability_pct,
            )
            for day_index in range(3)
        ],
        service_mode="test_weather",
    )
    return WeatherSnapshot(profile=profile, current=current, forecast=forecast)


class FakeMarketService:
    async def get_futures(self) -> MarketFuturesResponse:
        now = datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc)
        return MarketFuturesResponse(
            contracts=[
                FuturesContract(
                    market_key="arabica",
                    symbol="KCN26",
                    market="ICE Arabica",
                    price=248.7,
                    currency="US cents/lb",
                    change=4.7,
                    change_percent=1.9,
                    volume=35000,
                    volatility_pct=2.1,
                    contract_month="Jul 2026",
                    timestamp=now,
                    source_mode="test_market_feed",
                ),
                FuturesContract(
                    market_key="robusta",
                    symbol="RMN26",
                    market="ICE Europe Robusta",
                    price=2385.0,
                    currency="USD/tonne",
                    change=7.8,
                    change_percent=0.5,
                    volume=12000,
                    volatility_pct=1.2,
                    contract_month="Jul 2026",
                    timestamp=now,
                    source_mode="test_market_feed",
                ),
            ],
            timestamp=now,
            service_mode="test_market_feed",
        )


class FakeWeatherService:
    BRAZIL_REGIONS = {"Sul de Minas", "Cerrado Mineiro", "Espirito Santo"}

    async def get_snapshot(self, region: str, days: int = 3) -> WeatherSnapshot:
        _ = days
        if region in self.BRAZIL_REGIONS:
            return build_weather_snapshot(
                region,
                rainfall_mm=24.0,
                probability_pct=82.0,
                humidity_pct=84.0,
            )
        return build_weather_snapshot(
            region,
            rainfall_mm=6.0,
            probability_pct=46.0,
            humidity_pct=72.0,
        )


class FakeNewsService:
    async def get_latest(self, limit: int = 8, category: str = "prices") -> NewsFeedResponse:
        _ = category
        articles = [
            NewsArticle(
                title="Arabica prices firm as heavy rainfall threatens Brazil harvest pace",
                source="Coffee Wire",
                url="https://example.com/arabica-rain",
                published_at="2026-05-14",
                summary="Export desks flag weather risk and slower nearby availability.",
                category="prices",
            ),
            NewsArticle(
                title="Vietnam shipment pace stable as Robusta flows normalize",
                source="Trade Ledger",
                url="https://example.com/robusta-shipments",
                published_at="2026-05-14",
                summary="Robusta exporters report smoother logistics this week.",
                category="prices",
            ),
        ]
        return NewsFeedResponse(
            category="prices",
            count=min(limit, len(articles)),
            articles=articles[:limit],
            service_mode="test_news_feed",
        )


class TestFuturesHistoricalMemory(unittest.TestCase):
    def test_historical_memory_is_append_only_by_market_and_day(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            history_root = Path(temp_dir) / "futures_history"
            dummy_pipeline = SimpleNamespace(
                market_service=FakeMarketService(),
                weather_service=FakeWeatherService(),
                news_service=FakeNewsService(),
                rag_pipeline=SimpleNamespace(index_records=lambda records: len(records)),
                connectors={},
            )
            ingestor = FuturesIngestor(
                ingestion_pipeline=dummy_pipeline,
                history_root=history_root,
            )
            records = [
                {
                    "record_type": "futures_snapshot",
                    "metadata": {
                        "market": "arabica",
                        "price": 248.7,
                        "change_percent": 1.9,
                        "volatility_pct": 2.1,
                        "published_at": "2026-05-14T09:00:00+00:00",
                        "snapshot_date": "2026-05-14",
                    },
                    "raw": {"currency": "US cents/lb", "symbol": "KCN26"},
                },
                {
                    "record_type": "futures_snapshot",
                    "metadata": {
                        "market": "robusta",
                        "price": 2385.0,
                        "change_percent": 0.5,
                        "volatility_pct": 1.2,
                        "published_at": "2026-05-14T09:00:00+00:00",
                        "snapshot_date": "2026-05-14",
                    },
                    "raw": {"currency": "USD/tonne", "symbol": "RMN26"},
                },
            ]

            snapshots = ingestor.extract_historical_snapshots(records)
            first_write = ingestor.persist_historical_memory(snapshots)
            second_write = ingestor.persist_historical_memory(snapshots)

            self.assertEqual(first_write["snapshots_persisted"], 2)
            self.assertEqual(second_write["snapshots_persisted"], 0)
            self.assertEqual(second_write["snapshots_skipped"], 2)

            daily_entries = json.loads((history_root / "daily" / "2026-05-14.json").read_text(encoding="utf-8"))
            self.assertEqual(len(daily_entries), 2)
            self.assertEqual({item["market"] for item in daily_entries}, {"arabica", "robusta"})

            arabica_lines = (history_root / "markets" / "arabica.jsonl").read_text(encoding="utf-8").splitlines()
            robusta_lines = (history_root / "markets" / "robusta.jsonl").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(arabica_lines), 1)
            self.assertEqual(len(robusta_lines), 1)


class TestPredictiveIntelligence(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addAsyncCleanup(self._cleanup_temp_dir)
        self.history_root = Path(self.temp_dir.name) / "futures_history"
        (self.history_root / "markets").mkdir(parents=True, exist_ok=True)

        baseline_dates = [datetime(2026, 5, 9, tzinfo=timezone.utc) + timedelta(days=offset) for offset in range(5)]
        history_path = self.history_root / "markets" / "arabica.jsonl"
        with history_path.open("w", encoding="utf-8") as handle:
            for index, item_date in enumerate(baseline_dates, start=1):
                handle.write(
                    HistoricalFuturesSnapshot(
                        market="arabica",
                        price=244.0 + index,
                        change_percent=0.4 + (index * 0.05),
                        volatility=1.0 + (index * 0.04),
                        timestamp=item_date,
                        snapshot_date=item_date.date().isoformat(),
                        currency="US cents/lb",
                    ).model_dump_json()
                    + "\n"
                )

    async def _cleanup_temp_dir(self) -> None:
        self.temp_dir.cleanup()

    async def test_correlation_engine_detects_bullish_weather_and_news_alignment(self) -> None:
        engine = CorrelationEngine(history_root=self.history_root)
        snapshot = HistoricalFuturesSnapshot(
            market="arabica",
            price=248.7,
            change_percent=1.9,
            volatility=2.1,
            timestamp=datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc),
            snapshot_date="2026-05-14",
            currency="US cents/lb",
        )
        weather_context = {
            "arabica": [
                build_weather_snapshot("Sul de Minas", rainfall_mm=24.0, probability_pct=82.0, humidity_pct=84.0),
                build_weather_snapshot("Cerrado Mineiro", rainfall_mm=21.0, probability_pct=78.0, humidity_pct=80.0),
            ]
        }
        news_articles = [
            NewsArticle(
                title="Brazil rainfall delays Arabica harvest and tightens nearby supply",
                source="Coffee Desk",
                url="https://example.com/brazil-delay",
                published_at="2026-05-14",
                summary="Exporters cite weather concern and slower movement.",
                category="prices",
            )
        ]

        report = engine.analyze(
            futures_snapshots=[snapshot],
            weather_context=weather_context,
            news_articles=news_articles,
        )

        insight = report.insights[0]
        self.assertEqual(insight.direction, "bullish")
        self.assertIn("weather", [driver.driver_type for driver in insight.drivers])
        self.assertIn("news", [driver.driver_type for driver in insight.drivers])
        self.assertIn("rose", insight.causal_summary)

    async def test_risk_engine_scores_high_market_risk_from_brazil_weather_and_volatility(self) -> None:
        snapshot = HistoricalFuturesSnapshot(
            market="arabica",
            price=248.7,
            change_percent=1.9,
            volatility=2.1,
            timestamp=datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc),
            snapshot_date="2026-05-14",
            currency="US cents/lb",
        )
        weather_context = {
            "arabica": [
                build_weather_snapshot("Sul de Minas", rainfall_mm=24.0, probability_pct=82.0, humidity_pct=84.0),
                build_weather_snapshot("Cerrado Mineiro", rainfall_mm=21.0, probability_pct=78.0, humidity_pct=80.0),
            ]
        }
        news_articles = [
            NewsArticle(
                title="Brazil rainfall delays Arabica harvest and tightens nearby supply",
                source="Coffee Desk",
                url="https://example.com/brazil-delay",
                published_at="2026-05-14",
                summary="Exporters cite weather concern and slower movement.",
                category="prices",
            )
        ]
        correlations = CorrelationEngine(history_root=self.history_root).analyze(
            futures_snapshots=[snapshot],
            weather_context=weather_context,
            news_articles=news_articles,
        )

        assessment = RiskEngine(history_root=self.history_root).analyze(
            futures_snapshots=[snapshot],
            weather_context=weather_context,
            news_articles=news_articles,
            correlations=correlations,
        )

        self.assertEqual(assessment.market_risk, "HIGH")
        self.assertGreaterEqual(assessment.weather_risk, 0.75)
        self.assertGreaterEqual(assessment.volatility_risk, 0.65)
        self.assertIn("Brazil", assessment.explanation)

    async def test_alert_engine_generates_and_persists_decision_support_alerts(self) -> None:
        snapshot = HistoricalFuturesSnapshot(
            market="arabica",
            price=248.7,
            change_percent=1.9,
            volatility=2.1,
            timestamp=datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc),
            snapshot_date="2026-05-14",
            currency="US cents/lb",
        )
        weather_context = {
            "arabica": [
                build_weather_snapshot("Sul de Minas", rainfall_mm=24.0, probability_pct=82.0, humidity_pct=84.0),
                build_weather_snapshot("Cerrado Mineiro", rainfall_mm=21.0, probability_pct=78.0, humidity_pct=80.0),
            ]
        }
        news_articles = [
            NewsArticle(
                title="Brazil rainfall delays Arabica harvest and tightens nearby supply",
                source="Coffee Desk",
                url="https://example.com/brazil-delay",
                published_at="2026-05-14",
                summary="Exporters cite weather concern and slower movement.",
                category="prices",
            )
        ]
        correlations = CorrelationEngine(history_root=self.history_root).analyze(
            futures_snapshots=[snapshot],
            weather_context=weather_context,
            news_articles=news_articles,
        )
        assessment = RiskEngine(history_root=self.history_root).analyze(
            futures_snapshots=[snapshot],
            weather_context=weather_context,
            news_articles=news_articles,
            correlations=correlations,
        )
        alert_root = Path(self.temp_dir.name) / "decision_support_alerts"
        engine = AlertEngine(
            futures_history_root=self.history_root,
            alert_history_root=alert_root,
        )

        alert_feed = engine.generate(
            futures_snapshots=[snapshot],
            weather_context=weather_context,
            news_articles=news_articles,
            risk_assessment=assessment,
            correlations=correlations,
            generated_at=datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc),
        )
        persisted = engine.persist_alert_memory(alert_feed)

        self.assertGreaterEqual(alert_feed.count, 3)
        self.assertTrue(any("rainfall" in alert.title.lower() for alert in alert_feed.alerts))
        self.assertTrue(any("volatility" in alert.title.lower() for alert in alert_feed.alerts))
        self.assertGreaterEqual(int(persisted["alerts_persisted"]), 3)
        self.assertTrue((alert_root / "daily" / "2026-05-14.json").exists())

    async def test_market_snapshot_generator_builds_daily_intelligence_records(self) -> None:
        generator = MarketSnapshotGenerator(
            market_service=FakeMarketService(),
            weather_service=FakeWeatherService(),
            news_service=FakeNewsService(),
            correlation_engine=CorrelationEngine(history_root=self.history_root),
        )

        snapshot = await generator.generate()
        retrieval_records = generator.build_retrieval_records(snapshot)

        self.assertTrue(snapshot.headline.startswith("Arabica futures"))
        self.assertEqual(snapshot.sentiment, "constructive")
        self.assertIsNotNone(snapshot.risk_assessment)
        self.assertIsNotNone(snapshot.alert_feed)
        self.assertGreaterEqual(len(retrieval_records), 3)
        self.assertTrue(
            any(record["record_type"] == "market_intelligence_snapshot" for record in retrieval_records)
        )
        self.assertTrue(any(record["record_type"] == "market_risk_assessment" for record in retrieval_records))
        self.assertTrue(any(record["record_type"] == "market_intelligence_alert" for record in retrieval_records))


if __name__ == "__main__":
    unittest.main()
