from __future__ import annotations

import asyncio
import html
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from core.logger import logger
from .base import BaseConnector

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
        from datetime import datetime
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
