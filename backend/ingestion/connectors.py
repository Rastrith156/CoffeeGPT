from __future__ import annotations

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from abc import abstractmethod
from datetime import datetime
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from core.config import settings
from core.logger import logger
from models.schemas import CommodityVariety, HistoryWindow, NewsCategory, SourceDefinition


class BaseConnector:
    name = ""
    description = ""

    def descriptor(self) -> SourceDefinition:
        return SourceDefinition(name=self.name, description=self.description, enabled=True)

    def _record(
        self,
        title: str,
        content: str,
        record_type: str,
        raw: dict,
        metadata: dict,
    ) -> dict:
        return {
            "title": title,
            "content": content,
            "record_type": record_type,
            "raw": raw,
            "metadata": metadata,
        }

    @abstractmethod
    async def fetch(self) -> list[dict]:  # pragma: no cover
        raise NotImplementedError(f"{type(self).__name__} must implement fetch()")


class PriceConnector(BaseConnector):
    name = "prices"
    description = "Coffee spot and historical pricing intelligence"

    def __init__(self, market_service) -> None:
        self.market_service = market_service

    async def fetch(self) -> list[dict]:
        arabica = await self.market_service.get_prices(CommodityVariety.arabica, HistoryWindow.d30.value)
        robusta = await self.market_service.get_prices(CommodityVariety.robusta, HistoryWindow.d30.value)
        return [
            self._record(
                title="Arabica 30 day market curve",
                content=f"Arabica latest price is {arabica.latest} USD/lb with {arabica.change_pct}% change over 30 days.",
                record_type="market_prices",
                raw=arabica.model_dump(mode="json"),
                metadata={"source": self.name, "title": "Arabica 30 day market curve"},
            ),
            self._record(
                title="Robusta 30 day market curve",
                content=f"Robusta latest price is {robusta.latest} USD/lb with {robusta.change_pct}% change over 30 days.",
                record_type="market_prices",
                raw=robusta.model_dump(mode="json"),
                metadata={"source": self.name, "title": "Robusta 30 day market curve"},
            ),
        ]


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

        for region, snapshot in zip(regions, snapshots, strict=False):
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
        return " ".join(html.unescape(str(value or "")).split()).strip()


class NewsConnector(BaseConnector):
    name = "news"
    description = "Coffee news and macro-intelligence feed"

    USER_AGENT = "CoffeeGPT/1.0 (+https://localhost)"
    GOOGLE_NEWS_BASE = "https://news.google.com/rss/search"
    COFFEE_BOARD_URL = "https://coffeeboard.gov.in/News.aspx"
    GCP_LATEST_URL = "https://www.globalcoffeeplatform.org/latest/"
    COFFEE_KEYWORDS = ("coffee", "arabica", "robusta", "cafe", "espresso", "starbucks")
    GENERIC_LINK_TITLES = {"learn more", "read more", "latest", "follow us"}
    BLOCKED_TERMS = (
        "market size",
        "industry report",
        "growth report",
        "trade ideas",
        "statista",
        "indexbox",
        "tradingview",
        "finviz",
        "expected to reach us$",
        "2034",
        "2026-2034",
    )

    def __init__(self, news_service) -> None:
        self.news_service = news_service

    async def fetch(self) -> list[dict]:
        async with httpx.AsyncClient(
            timeout=12,
            follow_redirects=True,
            headers={"User-Agent": self.USER_AGENT},
        ) as client:
            tasks = [
                self._fetch_primary_feed(),
                self._fetch_google_news_feed(
                    client=client,
                    query="coffee market arabica robusta when:7d",
                    source_name="news_rss",
                    channel="Google News coffee market",
                    record_type="rss_feed",
                    limit=6,
                ),
                self._fetch_google_news_feed(
                    client=client,
                    query="coffee market Reuters when:30d",
                    source_name="news_reuters",
                    channel="Reuters coffee search",
                    record_type="reuters_search",
                    limit=6,
                    title_filter=lambda title: "reuters" in title.lower() and self._has_coffee_keyword(title),
                ),
                self._fetch_scraped_global_coffee_platform(client),
                self._fetch_coffee_board_updates(client),
            ]
            channel_results = await asyncio.gather(*tasks, return_exceptions=True)

        records: list[dict] = []
        for result in channel_results:
            if isinstance(result, Exception):
                logger.warning("News connector sub-task failed: {}", result)
                continue
            records.extend(result)
        return self._deduplicate(records)

    async def _fetch_primary_feed(self) -> list[dict]:
        records: list[dict] = []
        feed = await self.news_service.get_latest(limit=10, category="all")
        if feed.service_mode.startswith("curated_"):
            logger.info("Skipping placeholder primary news feed because live NewsAPI credentials are not configured")
            return records
        for article in feed.articles:
            if self._is_low_signal_news(article.title, article.summary):
                continue
            records.append(
                self._build_news_record(
                    title=article.title,
                    summary=article.summary,
                    record_type="news_article",
                    raw=article.model_dump(mode="json"),
                    source_name="news_api",
                    url=article.url,
                    published_at=article.published_at,
                    channel=feed.service_mode,
                )
            )
        return records

    async def _fetch_google_news_feed(
        self,
        *,
        client: httpx.AsyncClient,
        query: str,
        source_name: str,
        channel: str,
        record_type: str,
        limit: int,
        title_filter=None,
    ) -> list[dict]:
        url = f"{self.GOOGLE_NEWS_BASE}?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
        response = await client.get(url)
        response.raise_for_status()

        root = ET.fromstring(response.text)
        channel_node = root.find("channel")
        if channel_node is None:
            return []

        records: list[dict] = []
        for item in channel_node.findall("item"):
            title = self._clean_text(item.findtext("title"))
            if not title:
                continue
            if title_filter and not title_filter(title):
                continue

            description = self._clean_html(item.findtext("description", ""))
            if self._is_low_signal_news(title, description):
                continue
            source_label = self._clean_text(item.findtext("source")) or channel
            source_url = ""
            source_tag = item.find("source")
            if source_tag is not None:
                source_url = source_tag.attrib.get("url", "")
            link = item.findtext("link") or source_url
            published_at = item.findtext("pubDate", "")

            records.append(
                self._build_news_record(
                    title=title,
                    summary=description,
                    record_type=record_type,
                    raw={
                        "title": title,
                        "description": description,
                        "link": link,
                        "published_at": published_at,
                        "source": source_label,
                        "source_url": source_url,
                    },
                    source_name=source_name,
                    url=link,
                    published_at=published_at,
                    channel=source_label,
                )
            )
            if len(records) >= limit:
                break
        return records

    async def _fetch_scraped_global_coffee_platform(self, client: httpx.AsyncClient) -> list[dict]:
        response = await client.get(self.GCP_LATEST_URL)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        article_candidates: list[tuple[str, str]] = []
        seen_urls: set[str] = set()
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()
            title = self._clean_text(anchor.get_text(" ", strip=True))
            if not href.startswith("https://www.globalcoffeeplatform.org/latest/"):
                continue
            if not re.search(r"/latest/\d{4}/", href):
                continue
            if title.lower() in self.GENERIC_LINK_TITLES:
                continue
            if not title or href in seen_urls:
                continue
            article_candidates.append((title, href))
            seen_urls.add(href)
            if len(article_candidates) >= 4:
                break

        article_results = await asyncio.gather(
            *[self._scrape_gcp_article(client, title, url) for title, url in article_candidates],
            return_exceptions=True,
        )

        records: list[dict] = []
        for result in article_results:
            if isinstance(result, Exception):
                logger.warning("Global Coffee Platform scrape failed: {}", result)
                continue
            if result is not None:
                records.append(result)
        return records

    async def _scrape_gcp_article(
        self,
        client: httpx.AsyncClient,
        title: str,
        url: str,
    ) -> dict | None:
        response = await client.get(url)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        paragraphs: list[str] = []
        for paragraph in soup.find_all("p"):
            text = self._clean_text(paragraph.get_text(" ", strip=True))
            if text:
                paragraphs.append(text)
            if len(paragraphs) >= 3:
                break

        summary = " ".join(paragraphs[:2])
        if self._is_low_signal_news(title, summary):
            return None
        content = "\n".join(
            line
            for line in [
                title,
                summary or "Article scraped from Global Coffee Platform latest updates.",
                f"Source URL: {url}",
            ]
            if line
        )
        return self._record(
            title=title,
            content=content,
            record_type="scraped_news",
            raw={"title": title, "url": url, "summary": summary},
            metadata={
                "source": "news_scraper",
                "title": title,
                "url": url,
                "channel": "Global Coffee Platform latest",
            },
        )

    async def _fetch_coffee_board_updates(self, client: httpx.AsyncClient) -> list[dict]:
        response = await client.get(self.COFFEE_BOARD_URL)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        strings = [self._clean_text(text) for text in soup.stripped_strings]

        records: list[dict] = []
        seen_titles: set[str] = set()
        for index, value in enumerate(strings):
            if not re.fullmatch(r"\d{2}/\d{2}/\d{4}", value):
                continue
            if index + 1 >= len(strings):
                continue

            title = strings[index + 1]
            normalized_title = title.lower()
            if not title or normalized_title in seen_titles:
                continue
            seen_titles.add(normalized_title)

            published_at = self._normalize_board_date(value)
            records.append(
                self._build_news_record(
                    title=title,
                    summary=f"Official Coffee Board update published on {published_at}.",
                    record_type="coffee_board_update",
                    raw={"title": title, "published_at": published_at, "url": self.COFFEE_BOARD_URL},
                    source_name="news_board",
                    url=self.COFFEE_BOARD_URL,
                    published_at=published_at,
                    channel="Coffee Board of India",
                )
            )
            if len(records) >= 6:
                break
        return records

    def _build_news_record(
        self,
        *,
        title: str,
        summary: str,
        record_type: str,
        raw: dict,
        source_name: str,
        url: str,
        published_at: str,
        channel: str,
    ) -> dict:
        content_lines = [title]
        if summary:
            content_lines.append(summary)
        if published_at:
            content_lines.append(f"Published: {published_at}")
        if channel:
            content_lines.append(f"Channel: {channel}")
        if url:
            content_lines.append(f"Source URL: {url}")

        return self._record(
            title=title,
            content="\n".join(content_lines),
            record_type=record_type,
            raw=raw,
            metadata={
                "source": source_name,
                "title": title,
                "url": url,
                "published_at": published_at,
                "channel": channel,
            },
        )

    def _deduplicate(self, records: list[dict]) -> list[dict]:
        deduped: list[dict] = []
        seen_keys: set[tuple[str, str]] = set()
        for record in records:
            metadata = record.get("metadata") or {}
            url = str(metadata.get("url") or "").strip()
            title = str(record.get("title") or "").strip()
            raw = record.get("raw") or {}
            summary = str(raw.get("summary") or raw.get("description") or "").strip()
            if self._is_low_signal_news(title, summary):
                continue
            key = (url.lower(), title.lower())
            if not any(key):
                key = ("", title.lower())
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped.append(record)
        return deduped

    def _normalize_board_date(self, value: str) -> str:
        try:
            return datetime.strptime(value, "%d/%m/%Y").date().isoformat()
        except ValueError:
            return value

    def _clean_text(self, value: str | None) -> str:
        if not value:
            return ""
        return " ".join(html.unescape(value).split())

    def _clean_html(self, value: str) -> str:
        if not value:
            return ""
        soup = BeautifulSoup(value, "html.parser")
        text = soup.get_text(" ", strip=True)
        return self._clean_text(text)

    def _has_coffee_keyword(self, title: str) -> bool:
        lowered = title.lower()
        return any(keyword in lowered for keyword in self.COFFEE_KEYWORDS)

    def _is_low_signal_news(self, title: str, summary: str = "") -> bool:
        lowered = f"{title} {summary}".lower()
        return any(term in lowered for term in self.BLOCKED_TERMS)


class WeatherConnector(BaseConnector):
    name = "weather"
    description = "Growing region weather observations"

    def __init__(self, weather_service, regions: list[str]) -> None:
        self.weather_service = weather_service
        self.regions = regions

    async def fetch(self) -> list[dict]:
        records = []
        for region in self.regions:
            snapshot = await self.weather_service.get_snapshot(region=region, days=settings.weather_forecast_days)
            current = snapshot.current
            forecast = snapshot.forecast
            profile = snapshot.profile
            current_timestamp = current.timestamp.isoformat()
            snapshot_date = current.timestamp.date().isoformat()
            region_key = self._region_key(profile.name)

            records.append(
                self._record(
                    title=f"{profile.name} current weather",
                    content=(
                        f"{profile.name} current coffee weather: temperature {current.temperature_c} C, "
                        f"humidity {current.humidity_pct}%, precipitation {current.rainfall_mm} mm, "
                        f"wind {current.wind_speed_ms} m/s, conditions {current.description}. "
                        f"Observed at {current_timestamp}."
                    ),
                    record_type="weather_current",
                    raw={
                        "region": profile.name,
                        "country": profile.country,
                        "lat": current.lat,
                        "lon": current.lon,
                        "current": current.model_dump(mode="json"),
                        "service_mode": current.service_mode,
                    },
                    metadata={
                        "source": self.name,
                        "title": f"{profile.name} current weather",
                        "document_id": f"weather_current::{region_key}::{snapshot_date}",
                        "region": profile.name,
                        "country": profile.country,
                        "published_at": current_timestamp,
                        "snapshot_date": snapshot_date,
                        "lat": current.lat,
                        "lon": current.lon,
                    },
                )
            )

            forecast_lines = []
            for point in forecast.forecast[:3]:
                forecast_lines.append(
                    f"{point.date}: rain {point.rainfall_mm} mm, humidity {point.humidity_pct}%, "
                    f"temp {point.temp_c} C, wind {point.wind_speed_ms} m/s, precip probability "
                    f"{point.precipitation_probability_pct}%"
                )

            records.append(
                self._record(
                    title=f"{profile.name} weather outlook",
                    content=(
                        f"{profile.name} {forecast.days}-day coffee weather outlook. "
                        f"Current conditions remain {current.description} with humidity {current.humidity_pct}% and "
                        f"precipitation {current.rainfall_mm} mm. "
                        f"Near-term forecast: {'; '.join(forecast_lines)}."
                    ),
                    record_type="weather_forecast",
                    raw={
                        "region": profile.name,
                        "country": profile.country,
                        "lat": current.lat,
                        "lon": current.lon,
                        "current": current.model_dump(mode="json"),
                        "forecast": [point.model_dump(mode="json") for point in forecast.forecast],
                        "service_mode": forecast.service_mode,
                    },
                    metadata={
                        "source": self.name,
                        "title": f"{profile.name} weather outlook",
                        "document_id": f"weather_forecast::{region_key}::{snapshot_date}",
                        "region": profile.name,
                        "country": profile.country,
                        "published_at": current_timestamp,
                        "snapshot_date": snapshot_date,
                        "lat": current.lat,
                        "lon": current.lon,
                    },
                )
            )
        return records

    def _region_key(self, region: str) -> str:
        return region.lower().replace(" ", "_").replace("-", "_")


class PolicyConnector(BaseConnector):
    name = "policies"
    description = "Government and buyer policy tracker"

    def __init__(self, news_service) -> None:
        self.news_service = news_service

    async def fetch(self) -> list[dict]:
        updates = await self.news_service.get_policy_updates()
        return [
            self._record(
                title=policy.title,
                content=f"{policy.country}: {policy.title}. Status: {policy.status}. Impact: {policy.impact}.",
                record_type="policy_update",
                raw=policy.model_dump(mode="json"),
                metadata={"source": self.name, "title": policy.title},
            )
            for policy in updates.policies
        ]


class ExportConnector(BaseConnector):
    name = "exports"
    description = "Export volume and value intelligence"

    def __init__(self, market_service) -> None:
        self.market_service = market_service

    async def fetch(self) -> list[dict]:
        exports = await self.market_service.get_exports()
        return [
            self._record(
                title=f"{record.country} export profile",
                content=(
                    f"{record.country} exported {record.volume_bags_60kg} bags worth "
                    f"{record.value_usd_m} million USD."
                ),
                record_type="export_profile",
                raw=record.model_dump(mode="json"),
                metadata={"source": self.name, "title": f"{record.country} export profile"},
            )
            for record in exports.exports
        ]


class BuyerConnector(BaseConnector):
    name = "buyers"
    description = "Buyer signals and procurement posture"

    async def fetch(self) -> list[dict]:
        buyers = [
            {
                "buyer": "Specialty Roasters North America",
                "segment": "specialty",
                "signal": "seeking traceable washed Arabica lots",
            },
            {
                "buyer": "European Retail Blend Desk",
                "segment": "mainstream",
                "signal": "stable Robusta coverage for next 2 quarters",
            },
        ]
        return [
            self._record(
                title=item["buyer"],
                content=f"{item['buyer']} in {item['segment']} segment is {item['signal']}.",
                record_type="buyer_signal",
                raw=item,
                metadata={"source": self.name, "title": item["buyer"]},
            )
            for item in buyers
        ]


class LocalMarketConnector(BaseConnector):
    name = "local_markets"
    description = "Hyperlocal physical market observations"

    async def fetch(self) -> list[dict]:
        local_markets = [
            {
                "market": "Kochere Station Market",
                "country": "Ethiopia",
                "observation": "higher cherry competition among exporters",
            },
            {
                "market": "Huila Cooperative Board",
                "country": "Colombia",
                "observation": "quality differentials holding firm for washed lots",
            },
        ]
        return [
            self._record(
                title=item["market"],
                content=f"{item['market']} in {item['country']} reports {item['observation']}.",
                record_type="local_market_signal",
                raw=item,
                metadata={"source": self.name, "title": item["market"]},
            )
            for item in local_markets
        ]


def build_connectors(market_service, weather_service, news_service, regions: list[str]) -> dict[str, BaseConnector]:
    return {
        "prices": PriceConnector(market_service),
        "futures": FuturesConnector(market_service, weather_service, news_service),
        "news": NewsConnector(news_service),
        "weather": WeatherConnector(weather_service, regions),
        "policies": PolicyConnector(news_service),
        "exports": ExportConnector(market_service),
        "buyers": BuyerConnector(),
        "local_markets": LocalMarketConnector(),
    }
