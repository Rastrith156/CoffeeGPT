from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from core.dependencies import get_news_service
from models.schemas import NewsCategory, NewsFeedResponse, PolicyUpdatesResponse, SentimentSummaryResponse

router = APIRouter()


@router.get("/news/latest", response_model=NewsFeedResponse)
async def get_latest_news(
    limit: int = Query(default=20, ge=1, le=100),
    category: NewsCategory = Query(default=NewsCategory.all),
    news_service=Depends(get_news_service),
) -> NewsFeedResponse:
    return await news_service.get_latest(limit=limit, category=category.value)


@router.get("/news/sentiment", response_model=SentimentSummaryResponse)
async def get_sentiment(news_service=Depends(get_news_service)) -> SentimentSummaryResponse:
    return await news_service.get_sentiment_summary()


@router.get("/news/policies", response_model=PolicyUpdatesResponse)
async def get_policies(
    country: str | None = Query(default=None, description="Filter by country ISO-3 or bloc"),
    news_service=Depends(get_news_service),
) -> PolicyUpdatesResponse:
    return await news_service.get_policy_updates(country=country)
