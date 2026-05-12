from __future__ import annotations

from datetime import datetime, timezone

from forecasting.engine import CoffeeForecastEngine
from models.schemas import (
    CommodityVariety,
    DemandForecastResponse,
    PriceForecastResponse,
    SupplyRiskResponse,
)
from services.market_service import MarketService
from services.weather_service import WeatherService


class ForecastService:
    def __init__(
        self,
        engine: CoffeeForecastEngine | None = None,
        market_service: MarketService | None = None,
        weather_service: WeatherService | None = None,
    ) -> None:
        self.engine = engine or CoffeeForecastEngine()
        self.market_service = market_service or MarketService()
        self.weather_service = weather_service or WeatherService()

    async def forecast_price(
        self,
        variety: CommodityVariety = CommodityVariety.arabica,
        horizon_days: int = 30,
    ) -> PriceForecastResponse:
        return self.engine.build_price_forecast(variety=variety, horizon_days=horizon_days)

    async def forecast_demand(self, region: str = "global", horizon_months: int = 3) -> DemandForecastResponse:
        return self.engine.build_demand_forecast(region=region, horizon_months=horizon_months)

    async def supply_risk_assessment(self) -> SupplyRiskResponse:
        brazil_risk = await self.weather_service.get_risk_assessment("Minas Gerais")
        ethiopia_risk = await self.weather_service.get_risk_assessment("Yirgacheffe")
        colombia_risk = await self.weather_service.get_risk_assessment("Huila")
        market_summary = await self.market_service.get_ai_summary()

        scores = {
            "brazil_weather": max(signal.score for signal in brazil_risk.risks),
            "ethiopia_weather": max(signal.score for signal in ethiopia_risk.risks),
            "colombia_weather": max(signal.score for signal in colombia_risk.risks),
            "market_tightness": 0.68 if market_summary.sentiment == "cautiously_bullish" else 0.42,
        }
        risk_score = round(sum(scores.values()) / len(scores), 2)
        if risk_score >= 0.7:
            overall_risk = "high"
        elif risk_score >= 0.45:
            overall_risk = "moderate"
        else:
            overall_risk = "low"

        return SupplyRiskResponse(
            overall_risk=overall_risk,
            risk_score=risk_score,
            factors={
                key: {
                    "score": value,
                    "risk": "high" if value >= 0.7 else "moderate" if value >= 0.45 else "low",
                }
                for key, value in scores.items()
            },
            assessed_at=datetime.now(timezone.utc),
            engine=self.engine.metadata(),
        )
