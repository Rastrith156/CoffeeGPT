from __future__ import annotations

from fastapi import APIRouter, Depends

from core.dependencies import get_forecast_service
from models.schemas import (
    AlertFeedResponse,
    DemandForecastRequest,
    DemandForecastResponse,
    MarketCorrelationResponse,
    MarketIntelligenceSnapshotResponse,
    MarketRiskAssessmentResponse,
    PriceForecastRequest,
    PriceForecastResponse,
    SupplyRiskResponse,
)

router = APIRouter()


@router.post("/forecast/price", response_model=PriceForecastResponse)
async def forecast_price(
    request: PriceForecastRequest,
    forecast_service=Depends(get_forecast_service),
) -> PriceForecastResponse:
    return await forecast_service.forecast_price(
        variety=request.variety,
        horizon_days=request.horizon_days,
    )


@router.post("/forecast/demand", response_model=DemandForecastResponse)
async def forecast_demand(
    request: DemandForecastRequest,
    forecast_service=Depends(get_forecast_service),
) -> DemandForecastResponse:
    return await forecast_service.forecast_demand(
        region=request.region,
        horizon_months=request.horizon_months,
    )


@router.get("/forecast/supply", response_model=SupplyRiskResponse)
async def forecast_supply_risk(forecast_service=Depends(get_forecast_service)) -> SupplyRiskResponse:
    return await forecast_service.supply_risk_assessment()


@router.get("/forecast/correlations", response_model=MarketCorrelationResponse)
async def forecast_market_correlations(forecast_service=Depends(get_forecast_service)) -> MarketCorrelationResponse:
    return await forecast_service.market_correlations()


@router.get("/forecast/market-risk", response_model=MarketRiskAssessmentResponse)
async def forecast_market_risk(
    forecast_service=Depends(get_forecast_service),
) -> MarketRiskAssessmentResponse:
    return await forecast_service.market_risk_assessment()


@router.get("/forecast/alerts", response_model=AlertFeedResponse)
async def forecast_market_alerts(
    forecast_service=Depends(get_forecast_service),
) -> AlertFeedResponse:
    return await forecast_service.market_alerts()


@router.get("/forecast/market-snapshot", response_model=MarketIntelligenceSnapshotResponse)
async def forecast_market_snapshot(
    forecast_service=Depends(get_forecast_service),
) -> MarketIntelligenceSnapshotResponse:
    return await forecast_service.market_intelligence_snapshot()
