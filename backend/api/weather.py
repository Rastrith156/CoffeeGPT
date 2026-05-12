from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from core.dependencies import get_weather_service
from models.schemas import RiskAssessmentResponse, WeatherCurrentResponse, WeatherForecastResponse

router = APIRouter()


@router.get("/weather/current", response_model=WeatherCurrentResponse)
async def get_current_weather(
    region: str = Query(default="Yirgacheffe"),
    lat: float | None = Query(default=None),
    lon: float | None = Query(default=None),
    weather_service=Depends(get_weather_service),
) -> WeatherCurrentResponse:
    return await weather_service.get_current(region=region, lat=lat, lon=lon)


@router.get("/weather/forecast", response_model=WeatherForecastResponse)
async def get_forecast(
    region: str = Query(default="Yirgacheffe"),
    days: int = Query(default=7, ge=1, le=14),
    weather_service=Depends(get_weather_service),
) -> WeatherForecastResponse:
    return await weather_service.get_forecast(region=region, days=days)


@router.get("/weather/risks", response_model=RiskAssessmentResponse)
async def get_risks(
    region: str = Query(default="Yirgacheffe"),
    weather_service=Depends(get_weather_service),
) -> RiskAssessmentResponse:
    return await weather_service.get_risk_assessment(region=region)
