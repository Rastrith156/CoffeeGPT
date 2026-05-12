from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone

import httpx
from loguru import logger

from core.config import settings
from models.schemas import (
    RiskAssessmentResponse,
    RiskSignal,
    WeatherCurrentResponse,
    WeatherForecastPoint,
    WeatherForecastResponse,
)

REGION_COORDS = {
    "yirgacheffe": (6.1500, 38.2000),
    "sidama": (6.7500, 38.5000),
    "minas gerais": (-19.9167, -43.9345),
    "huila": (2.5359, -75.5277),
    "sumatra": (3.5952, 98.6722),
    "kilimanjaro": (-3.0674, 37.3556),
}


class WeatherService:
    BASE_URL = "https://api.openweathermap.org/data/2.5"

    def _get_coords(self, region: str, lat: float | None = None, lon: float | None = None) -> tuple[float, float]:
        if lat is not None and lon is not None:
            return lat, lon
        return REGION_COORDS.get(region.lower(), (6.15, 38.20))

    def _risk_level(self, score: float) -> str:
        if score >= 0.75:
            return "high"
        if score >= 0.45:
            return "moderate"
        if score >= 0.2:
            return "low"
        return "minimal"

    async def get_current(
        self,
        region: str,
        lat: float | None = None,
        lon: float | None = None,
    ) -> WeatherCurrentResponse:
        resolved_lat, resolved_lon = self._get_coords(region, lat, lon)
        if not settings.openweather_api_key:
            return self._demo_current(region, resolved_lat, resolved_lon)

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.BASE_URL}/weather",
                    params={
                        "lat": resolved_lat,
                        "lon": resolved_lon,
                        "appid": settings.openweather_api_key,
                        "units": "metric",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.warning("Weather API failed, using demo data: {}", exc)
            return self._demo_current(region, resolved_lat, resolved_lon)

        return WeatherCurrentResponse(
            region=region,
            lat=resolved_lat,
            lon=resolved_lon,
            temperature_c=float(payload["main"]["temp"]),
            humidity_pct=float(payload["main"]["humidity"]),
            rainfall_mm=float(payload.get("rain", {}).get("1h", 0.0)),
            wind_speed_ms=float(payload["wind"]["speed"]),
            description=payload["weather"][0]["description"],
            timestamp=datetime.now(timezone.utc),
            service_mode="live_openweather",
        )

    async def get_forecast(self, region: str, days: int = 7) -> WeatherForecastResponse:
        resolved_lat, resolved_lon = self._get_coords(region)
        if settings.openweather_api_key:
            live_forecast = await self._live_forecast(region, resolved_lat, resolved_lon, days)
            if live_forecast:
                return live_forecast
        return self._demo_forecast(region, resolved_lat, resolved_lon, days)

    async def get_risk_assessment(self, region: str) -> RiskAssessmentResponse:
        forecast = await self.get_forecast(region, days=5)
        avg_humidity = sum(point.humidity_pct for point in forecast.forecast) / len(forecast.forecast)
        avg_rainfall = sum(point.rainfall_mm for point in forecast.forecast) / len(forecast.forecast)
        min_temp = min(point.temp_c for point in forecast.forecast)

        rust_score = min(0.95, 0.12 + (avg_humidity / 100.0) * 0.68 + min(avg_rainfall, 12.0) / 30.0)
        berry_score = min(0.9, 0.08 + (avg_rainfall / 18.0) + (avg_humidity / 220.0))
        drought_score = max(0.05, 0.7 - (avg_rainfall / 16.0))
        frost_score = 0.65 if min_temp <= 4 else 0.05

        risks = [
            RiskSignal(
                name="coffee_leaf_rust",
                level=self._risk_level(rust_score),
                score=round(rust_score, 2),
                trigger=f"avg humidity {avg_humidity:.1f}%",
            ),
            RiskSignal(
                name="coffee_berry_disease",
                level=self._risk_level(berry_score),
                score=round(berry_score, 2),
                trigger=f"avg rainfall {avg_rainfall:.1f} mm",
            ),
            RiskSignal(
                name="drought",
                level=self._risk_level(drought_score),
                score=round(drought_score, 2),
                trigger=f"avg rainfall {avg_rainfall:.1f} mm",
            ),
            RiskSignal(
                name="frost",
                level=self._risk_level(frost_score),
                score=round(frost_score, 2),
                trigger=f"min temp {min_temp:.1f} C",
            ),
        ]
        overall_score = max(item.score for item in risks)

        return RiskAssessmentResponse(
            region=region,
            risks=risks,
            overall_risk=self._risk_level(overall_score),
            assessed_at=datetime.now(timezone.utc),
            service_mode=forecast.service_mode,
        )

    async def _live_forecast(
        self,
        region: str,
        lat: float,
        lon: float,
        days: int,
    ) -> WeatherForecastResponse | None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.BASE_URL}/forecast",
                    params={
                        "lat": lat,
                        "lon": lon,
                        "appid": settings.openweather_api_key,
                        "units": "metric",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            logger.warning("Weather forecast API failed, using demo data: {}", exc)
            return None

        daily_values: dict[str, list[dict]] = defaultdict(list)
        for item in payload.get("list", []):
            day_key = item["dt_txt"].split(" ")[0]
            daily_values[day_key].append(item)

        points: list[WeatherForecastPoint] = []
        for index, (day_key, items) in enumerate(list(daily_values.items())[:days], start=1):
            points.append(
                WeatherForecastPoint(
                    day=index,
                    date=day_key,
                    temp_c=round(sum(entry["main"]["temp"] for entry in items) / len(items), 1),
                    humidity_pct=round(sum(entry["main"]["humidity"] for entry in items) / len(items), 1),
                    rainfall_mm=round(sum(entry.get("rain", {}).get("3h", 0.0) for entry in items), 1),
                )
            )

        return WeatherForecastResponse(
            region=region,
            days=len(points),
            forecast=points,
            service_mode="live_openweather",
        )

    def _demo_current(self, region: str, lat: float, lon: float) -> WeatherCurrentResponse:
        return WeatherCurrentResponse(
            region=region,
            lat=lat,
            lon=lon,
            temperature_c=19.4,
            humidity_pct=74.0,
            rainfall_mm=3.2,
            wind_speed_ms=2.1,
            description="partly cloudy",
            timestamp=datetime.now(timezone.utc),
            service_mode="demo_weather_profile",
        )

    def _demo_forecast(self, region: str, lat: float, lon: float, days: int) -> WeatherForecastResponse:
        today = datetime.now(timezone.utc)
        forecast = [
            WeatherForecastPoint(
                day=index + 1,
                date=(today + timedelta(days=index + 1)).date().isoformat(),
                temp_c=round(18.8 + (index * 0.35), 1),
                humidity_pct=round(76.0 - index, 1),
                rainfall_mm=round(max(0.8, 5.6 - (index * 0.55)), 1),
            )
            for index in range(days)
        ]
        return WeatherForecastResponse(
            region=region,
            days=days,
            forecast=forecast,
            service_mode="demo_weather_profile",
        )
