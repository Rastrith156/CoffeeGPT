from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx

from core.config import settings
from core.logger import logger
from models.schemas import (
    NewsArticle,
    NewsCategory,
    NewsFeedResponse,
    PolicyUpdate,
    PolicyUpdatesResponse,
    SentimentSummaryResponse,
)


class NewsService:
    NEWSAPI_URL = "https://newsapi.org/v2/everything"
    CATEGORIES = {
        NewsCategory.all.value: "coffee",
        NewsCategory.prices.value: "coffee prices arabica robusta futures",
        NewsCategory.policy.value: "coffee policy export regulation tariff",
        NewsCategory.weather.value: "coffee weather drought rainfall crop",
        NewsCategory.trade.value: "coffee trade export demand buyers",
    }

    async def get_latest(self, limit: int = 20, category: str = NewsCategory.all.value) -> NewsFeedResponse:
        if not settings.newsapi_key:
            return self._demo_articles(limit, category)

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    self.NEWSAPI_URL,
                    params={
                        "q": self.CATEGORIES.get(category, "coffee"),
                        "language": "en",
                        "sortBy": "publishedAt",
                        "pageSize": limit,
                        "apiKey": settings.newsapi_key,
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.warning("News API failed, using curated feed: {}", exc)
            return self._demo_articles(limit, category)

        articles = [
            NewsArticle(
                title=item["title"],
                source=item["source"]["name"],
                url=item["url"],
                published_at=item["publishedAt"],
                summary=item.get("description") or "",
                category=category,
            )
            for item in payload.get("articles", [])
        ]
        return NewsFeedResponse(
            category=category,
            count=len(articles),
            articles=articles,
            service_mode="live_newsapi",
        )

    async def get_sentiment_summary(self) -> SentimentSummaryResponse:
        feed = await self.get_latest(limit=6, category=NewsCategory.all.value)
        titles = " ".join(article.title.lower() for article in feed.articles)
        bullish_hits = sum(token in titles for token in ("surge", "growth", "rebound", "strong"))
        cautious_hits = sum(token in titles for token in ("drought", "risk", "delay", "pressure"))
        score = round(0.52 + (bullish_hits * 0.04) - (cautious_hits * 0.03), 2)
        return SentimentSummaryResponse(
            overall_sentiment="constructive" if score >= 0.55 else "mixed",
            score=max(0.1, min(score, 0.95)),
            signals={
                "price_sentiment": "bullish" if "surge" in titles or "rebound" in titles else "balanced",
                "supply_sentiment": "cautious" if "drought" in titles or "risk" in titles else "stable",
                "demand_sentiment": "steady",
            },
            top_themes=[
                "global export flows",
                "weather volatility",
                "buyer demand patterns",
                "policy compliance",
            ],
            generated_at=datetime.now(timezone.utc),
            service_mode=feed.service_mode,
        )

    async def get_policy_updates(self, country: str | None = None) -> PolicyUpdatesResponse:
        policies = [
            PolicyUpdate(
                country="EU",
                title="EUDR compliance rollout for coffee traceability",
                status="preparation_phase",
                impact="high",
                date="2026-02-15",
            ),
            PolicyUpdate(
                country="BRA",
                title="Brazil export logistics modernization package",
                status="under_review",
                impact="medium",
                date="2026-01-28",
            ),
            PolicyUpdate(
                country="VNM",
                title="Vietnam quality benchmark revision for Robusta exports",
                status="implemented",
                impact="medium",
                date="2025-12-11",
            ),
            PolicyUpdate(
                country="ETH",
                title="Ethiopia coffee auction transparency reform",
                status="proposed",
                impact="medium",
                date="2026-03-04",
            ),
        ]
        if country:
            policies = [item for item in policies if item.country.upper() == country.upper()]
        return PolicyUpdatesResponse(
            policies=policies,
            count=len(policies),
            fetched_at=datetime.now(timezone.utc),
            service_mode="curated_policy_tracker",
        )

    def _demo_articles(self, limit: int, category: str) -> NewsFeedResponse:
        today = datetime.now(timezone.utc)
        articles = [
            NewsArticle(
                title="Arabica prices firm as dry weather risks remain in Brazil",
                source="Coffee Intelligence Wire",
                url="https://example.com/arabica-weather-risk",
                published_at=(today - timedelta(days=1)).date().isoformat(),
                summary="Exporters continue to watch moisture deficits in key Arabica zones.",
                category=category,
            ),
            NewsArticle(
                title="Vietnam shipment pace improves as buyer demand stabilizes",
                source="Global Trade Ledger",
                url="https://example.com/vietnam-shipment-pace",
                published_at=(today - timedelta(days=2)).date().isoformat(),
                summary="Robusta flow improves while forward contracting remains disciplined.",
                category=category,
            ),
            NewsArticle(
                title="Coffee policy teams prepare for stricter traceability workflows",
                source="Policy Brew",
                url="https://example.com/traceability-workflows",
                published_at=(today - timedelta(days=3)).date().isoformat(),
                summary="Large buyers expand readiness programs for origin-level compliance evidence.",
                category=category,
            ),
        ][:limit]
        return NewsFeedResponse(
            category=category,
            count=len(articles),
            articles=articles,
            service_mode="curated_news_feed",
        )
