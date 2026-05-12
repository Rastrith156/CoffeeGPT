from __future__ import annotations

import importlib.util
import math
from datetime import datetime, timedelta, timezone

from models.schemas import (
    CommodityVariety,
    DemandForecastPoint,
    DemandForecastResponse,
    ForecastEngineMetadata,
    PriceForecastPoint,
    PriceForecastResponse,
)


class CoffeeForecastEngine:
    def __init__(self) -> None:
        self.prophet_available = importlib.util.find_spec("prophet") is not None
        self.xgboost_available = importlib.util.find_spec("xgboost") is not None

    def metadata(self) -> ForecastEngineMetadata:
        if self.prophet_available and self.xgboost_available:
            engine_mode = "prophet_xgboost_ready"
        elif self.prophet_available or self.xgboost_available:
            engine_mode = "hybrid_partial_ready"
        else:
            engine_mode = "statistical_baseline"
        return ForecastEngineMetadata(
            engine_mode=engine_mode,
            prophet_available=self.prophet_available,
            xgboost_available=self.xgboost_available,
        )

    def build_price_forecast(
        self,
        variety: CommodityVariety,
        horizon_days: int,
    ) -> PriceForecastResponse:
        base_price = 1.86 if variety == CommodityVariety.arabica else 1.14
        drift = 0.0012 if variety == CommodityVariety.arabica else 0.0008
        today = datetime.now(timezone.utc)
        points: list[PriceForecastPoint] = []

        for day in range(1, horizon_days + 1):
            seasonal = math.sin(day / 5.0) * 0.018
            volatility = math.cos(day / 9.0) * 0.007
            forecast_price = round(base_price + (day * drift) + seasonal + volatility, 4)
            points.append(
                PriceForecastPoint(
                    date=(today + timedelta(days=day)).date().isoformat(),
                    forecast_usd_per_lb=forecast_price,
                    lower_80=round(forecast_price * 0.965, 4),
                    upper_80=round(forecast_price * 1.035, 4),
                )
            )

        return PriceForecastResponse(
            variety=variety,
            horizon_days=horizon_days,
            model="Prophet + XGBoost enterprise scaffold",
            engine=self.metadata(),
            forecast=points,
            summary={
                "current_price": base_price,
                "forecast_end_price": points[-1].forecast_usd_per_lb,
                "trend": "upward" if points[-1].forecast_usd_per_lb >= base_price else "downward",
            },
            generated_at=today,
        )

    def build_demand_forecast(self, region: str, horizon_months: int) -> DemandForecastResponse:
        today = datetime.now(timezone.utc)
        baseline = 11.4 if region.lower() == "global" else 2.6
        points: list[DemandForecastPoint] = []

        for month in range(1, horizon_months + 1):
            demand = round(baseline + (month * 0.14) + math.sin(month / 3.0) * 0.06, 2)
            points.append(
                DemandForecastPoint(
                    month=(today + timedelta(days=30 * month)).strftime("%Y-%m"),
                    demand_bags_m=demand,
                )
            )

        return DemandForecastResponse(
            region=region,
            horizon_months=horizon_months,
            engine=self.metadata(),
            forecast=points,
            generated_at=today,
        )
