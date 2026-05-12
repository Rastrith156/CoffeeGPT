from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from core.dependencies import get_market_service
from models.schemas import (
    CommodityVariety,
    HistoryWindow,
    MarketExportsResponse,
    MarketFuturesResponse,
    MarketPricesResponse,
    MarketSummaryResponse,
)

router = APIRouter()


@router.get("/market/prices", response_model=MarketPricesResponse)
async def get_prices(
    variety: CommodityVariety = Query(default=CommodityVariety.arabica),
    period: HistoryWindow = Query(default=HistoryWindow.d7),
    market_service=Depends(get_market_service),
) -> MarketPricesResponse:
    return await market_service.get_prices(variety=variety, period=period.value)


@router.get("/market/futures", response_model=MarketFuturesResponse)
async def get_futures(market_service=Depends(get_market_service)) -> MarketFuturesResponse:
    return await market_service.get_futures()


@router.get("/market/exports", response_model=MarketExportsResponse)
async def get_exports(
    country: str | None = Query(default=None, description="ISO-3 country code"),
    market_service=Depends(get_market_service),
) -> MarketExportsResponse:
    return await market_service.get_exports(country=country)


@router.get("/market/summary", response_model=MarketSummaryResponse)
async def get_market_summary(market_service=Depends(get_market_service)) -> MarketSummaryResponse:
    return await market_service.get_ai_summary()
