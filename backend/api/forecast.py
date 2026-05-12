from __future__ import annotations

from fastapi import APIRouter, Depends

from core.dependencies import get_forecast_service
from models.schemas import (
    DemandForecastRequest,
    DemandForecastResponse,
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
