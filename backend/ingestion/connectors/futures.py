from __future__ import annotations

import asyncio
from datetime import datetime

from core.logger import logger
from models.schemas import NewsCategory
from .base import BaseConnector

class FuturesConnector(BaseConnector):
    name = "futures"
    description = "Coffee futures snapshots and market intelligence"
    WEATHER_REGIONS = {
        "arabica": ("Sul de Minas", "Cerrado Mineiro", "Espirito Santo"),
        "robusta": ("Dak Lak", "Lam Dong", "Gia Lai"),
    }

    def __init__(self, market_service, weather_service, news_service) -> None:
        self.market_service = market_service
        self.weather_service = weather_service
        self.news_service = news_service

    async def fetch(self) -> list[dict]:
        futures = await self.market_service.get_futures()
        timestamp = futures.timestamp
        snapshot_date = timestamp.date().isoformat()
        latest_news = await self.news_service.get_latest(limit=4, category=NewsCategory.prices.value)
        records: list[dict] = []

        for contract in futures.contracts:
            published_at = self._contract_timestamp(contract, timestamp)
            weather_signal = await self._weather_signal(contract.market_key)
            news_headline = self._market_news_headline(contract.market_key, latest_news.articles)
            records.append(self._snapshot_record(contract, snapshot_date, published_at))
            records.append(
                self._summary_record(
                    contract=contract,
                    snapshot_date=snapshot_date,
                    published_at=published_at,
                    weather_signal=weather_signal,
                    news_headline=news_headline,
                    service_mode=futures.service_mode,
                )
            )

        records.append(
            self._cross_market_summary_record(
                contracts=futures.contracts,
                snapshot_date=snapshot_date,
                published_at=timestamp.isoformat(),
                service_mode=futures.service_mode,
            )
        )
        return records

    def _snapshot_record(self, contract, snapshot_date: str, published_at: str) -> dict:
        market_label = contract.market_key.capitalize()
        volume_text = (
            f"volume {contract.volume:,}, " if isinstance(contract.volume, int) and contract.volume > 0 else ""
        )
        open_interest_text = (
            f"open interest {contract.open_interest:,}, "
            if isinstance(contract.open_interest, int) and contract.open_interest > 0
            else ""
        )
        content = (
            f"{market_label} futures snapshot for {snapshot_date}. "
            f"{market_label} futures are at {contract.price} {contract.currency}, "
            f"{self._direction_word(contract.change_percent)} {abs(contract.change_percent):.2f}% "
            f"({contract.change:+.2f}) on the session, "
            f"{volume_text}{open_interest_text}estimated volatility {contract.volatility_pct:.2f}%."
        )
        return self._record(
            title=f"{market_label} futures snapshot",
            content=" ".join(content.split()),
            record_type="futures_snapshot",
            raw={
                **contract.model_dump(mode="json"),
                "snapshot_date": snapshot_date,
            },
            metadata={
                "source": self.name,
                "title": f"{market_label} futures snapshot",
                "document_id": f"futures_snapshot::{contract.market_key}::{snapshot_date}",
                "market": contract.market_key,
                "symbol": contract.symbol,
                "price": contract.price,
                "currency": contract.currency,
                "change_percent": contract.change_percent,
                "volatility_pct": contract.volatility_pct,
                "published_at": published_at,
                "snapshot_date": snapshot_date,
            },
        )

    def _summary_record(
        self,
        *,
        contract,
        snapshot_date: str,
        published_at: str,
        weather_signal: dict,
        news_headline: str,
        service_mode: str,
    ) -> dict:
        market_label = contract.market_key.capitalize()
        movement = self._movement_phrase(contract)
        weather_summary = str(weather_signal.get("summary") or "").strip()
        weather_regions = ", ".join(weather_signal.get("regions") or []) or "key producing regions"
        news_sentence = f" Recent market coverage includes {news_headline}." if news_headline else ""
        content = (
            f"{market_label} futures {movement} on {snapshot_date}. "
            f"{weather_summary} across {weather_regions}.{news_sentence} "
            f"Volatility is running near {contract.volatility_pct:.2f}%."
        )
        return self._record(
            title=f"{market_label} futures intelligence",
            content=" ".join(content.split()),
            record_type="futures_intelligence_summary",
            raw={
                "market_key": contract.market_key,
                "symbol": contract.symbol,
                "snapshot_date": snapshot_date,
                "price": contract.price,
                "change": contract.change,
                "change_percent": contract.change_percent,
                "volatility_pct": contract.volatility_pct,
                "weather_signal": weather_signal,
                "news_headline": news_headline,
                "service_mode": service_mode,
            },
            metadata={
                "source": self.name,
                "title": f"{market_label} futures intelligence",
                "document_id": f"futures_intelligence::{contract.market_key}::{snapshot_date}",
                "market": contract.market_key,
                "symbol": contract.symbol,
                "price": contract.price,
                "currency": contract.currency,
                "change_percent": contract.change_percent,
                "volatility_pct": contract.volatility_pct,
                "published_at": published_at,
                "snapshot_date": snapshot_date,
            },
        )

    def _cross_market_summary_record(
        self,
        *,
        contracts: list,
        snapshot_date: str,
        published_at: str,
        service_mode: str,
    ) -> dict:
        arabica = next((contract for contract in contracts if contract.market_key == "arabica"), None)
        robusta = next((contract for contract in contracts if contract.market_key == "robusta"), None)
        clauses = []
        if arabica is not None:
            clauses.append(
                f"Arabica at {arabica.price} {arabica.currency}, {arabica.change_percent:+.2f}% on the day"
            )
        if robusta is not None:
            clauses.append(
                f"Robusta at {robusta.price} {robusta.currency}, {robusta.change_percent:+.2f}% on the day"
            )
        tone = self._cross_market_tone(contracts)
        content = (
            f"Coffee futures cross-market summary for {snapshot_date}. "
            f"{'; '.join(clauses)}. "
            f"Overall tone is {tone}, with futures, weather, and supply expectations moving together in the daily signal set."
        )
        return self._record(
            title="Coffee futures cross-market summary",
            content=" ".join(content.split()),
            record_type="futures_cross_market_summary",
            raw={
                "snapshot_date": snapshot_date,
                "service_mode": service_mode,
                "contracts": [contract.model_dump(mode="json") for contract in contracts],
                "tone": tone,
            },
            metadata={
                "source": self.name,
                "title": "Coffee futures cross-market summary",
                "document_id": f"futures_cross_market_summary::global::{snapshot_date}",
                "market": "global",
                "published_at": published_at,
                "snapshot_date": snapshot_date,
            },
        )

    async def _weather_signal(self, market_key: str) -> dict:
        regions = list(self.WEATHER_REGIONS.get(market_key, ()))
        if not regions:
            return {"summary": "Weather signals are mixed", "regions": []}

        snapshots = await asyncio.gather(
            *[self.weather_service.get_snapshot(region=region, days=3) for region in regions],
            return_exceptions=True,
        )
        rainfall_values: list[float] = []
        humidity_values: list[float] = []
        probability_values: list[float] = []
        valid_regions: list[str] = []

        for region, snapshot in zip(regions, snapshots):
            if isinstance(snapshot, Exception):
                logger.warning("Weather snapshot failed for {} while building futures summary: {}", region, snapshot)
                continue
            valid_regions.append(region)
            rainfall_values.append(sum(point.rainfall_mm for point in snapshot.forecast.forecast[:3]))
            humidity_values.append(snapshot.current.humidity_pct)
            probability_values.append(
                max((point.precipitation_probability_pct for point in snapshot.forecast.forecast[:3]), default=0.0)
            )

        if not rainfall_values:
            return {"summary": "Weather signals are mixed", "regions": regions}

        avg_rainfall = sum(rainfall_values) / len(rainfall_values)
        avg_humidity = sum(humidity_values) / len(humidity_values)
        avg_probability = sum(probability_values) / len(probability_values)

        if avg_rainfall >= 18 or avg_probability >= 70:
            summary = f"Heavy rainfall risk remains elevated with roughly {avg_rainfall:.1f} mm forecast over the next three days"
        elif avg_rainfall >= 7:
            summary = f"Wet weather remains in play with around {avg_rainfall:.1f} mm forecast over the next three days"
        elif avg_rainfall <= 2 and avg_humidity <= 65:
            summary = f"Conditions are comparatively dry, with only {avg_rainfall:.1f} mm forecast over the next three days"
        else:
            summary = f"Weather signals are mixed, with around {avg_rainfall:.1f} mm forecast and humidity near {avg_humidity:.0f}%"

        return {
            "summary": summary,
            "regions": valid_regions or regions,
            "avg_rainfall_mm_3d": round(avg_rainfall, 2),
            "avg_humidity_pct": round(avg_humidity, 1),
            "avg_precip_probability_pct": round(avg_probability, 1),
        }

    def _market_news_headline(self, market_key: str, articles: list) -> str:
        if not articles:
            return ""
        for article in articles:
            title = self._clean_text(getattr(article, "title", ""))
            lowered = title.lower()
            if market_key == "arabica" and ("arabica" in lowered or "brazil" in lowered):
                return title
            if market_key == "robusta" and ("robusta" in lowered or "vietnam" in lowered):
                return title
        return self._clean_text(getattr(articles[0], "title", ""))

    def _movement_phrase(self, contract) -> str:
        direction = self._direction_word(contract.change_percent)
        return (
            f"are {direction} {abs(contract.change_percent):.2f}% to {contract.price} {contract.currency} "
            f"({contract.change:+.2f})"
        )

    def _direction_word(self, change_percent: float) -> str:
        if change_percent > 0.15:
            return "up"
        if change_percent < -0.15:
            return "down"
        return "little changed"

    def _cross_market_tone(self, contracts: list) -> str:
        positive = sum(1 for contract in contracts if contract.change_percent > 0.15)
        negative = sum(1 for contract in contracts if contract.change_percent < -0.15)
        if positive and not negative:
            return "constructive"
        if negative and not positive:
            return "defensive"
        return "mixed"

    def _contract_timestamp(self, contract, fallback: datetime) -> str:
        if contract.timestamp is not None:
            return contract.timestamp.isoformat()
        return fallback.isoformat()

    def _clean_text(self, value: str | None) -> str:
        import html
        return " ".join(html.unescape(str(value or "")).split()).strip()
