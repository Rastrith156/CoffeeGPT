from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter
import unicodedata

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from core.config import settings
from core.logger import logger
from models.schemas import (
    RiskAssessmentResponse,
    RiskSignal,
    WeatherCurrentResponse,
    WeatherForecastPoint,
    WeatherForecastResponse,
)
from streaming.dead_letter_queue import DeadLetterQueue



@dataclass(frozen=True, slots=True)
class WeatherRegionProfile:
    name: str
    country: str
    lat: float
    lon: float
    aliases: tuple[str, ...] = ()


@dataclass(slots=True)
class WeatherSnapshot:
    profile: WeatherRegionProfile
    current: WeatherCurrentResponse
    forecast: WeatherForecastResponse


REGION_PROFILES = (
    WeatherRegionProfile("Chikmagalur", "India", 13.3152, 75.7754, aliases=("chikkamagaluru",)),
    WeatherRegionProfile("Kodagu", "India", 12.4244, 75.7382, aliases=("coorg",)),
    WeatherRegionProfile("Hassan", "India", 13.0033, 76.1004),
    WeatherRegionProfile("Sakleshpur", "India", 12.9447, 75.7860),
    WeatherRegionProfile("Sul de Minas", "Brazil", -21.5513, -45.4303, aliases=("south minas",)),
    WeatherRegionProfile("Cerrado Mineiro", "Brazil", -18.9436, -46.9926, aliases=("cerrado",)),
    WeatherRegionProfile("Espirito Santo", "Brazil", -19.1834, -40.3089, aliases=("espirito", "espirito santo")),
    WeatherRegionProfile("Minas Gerais", "Brazil", -19.9167, -43.9345),
    WeatherRegionProfile("Dak Lak", "Vietnam", 12.7100, 108.2378, aliases=("daklak",)),
    WeatherRegionProfile("Lam Dong", "Vietnam", 11.9404, 108.4583, aliases=("dalat",)),
    WeatherRegionProfile("Gia Lai", "Vietnam", 13.9833, 108.0000),
    WeatherRegionProfile("Yirgacheffe", "Ethiopia", 6.1500, 38.2000),
    WeatherRegionProfile("Sidama", "Ethiopia", 6.7500, 38.5000),
    WeatherRegionProfile("Huila", "Colombia", 2.5359, -75.5277),
    WeatherRegionProfile("Sumatra", "Indonesia", 3.5952, 98.6722),
    WeatherRegionProfile("Kilimanjaro", "Tanzania", -3.0674, 37.3556),
)

WMO_CODE_DESCRIPTIONS = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    56: "light freezing drizzle",
    57: "dense freezing drizzle",
    61: "slight rain",
    63: "moderate rain",
    65: "heavy rain",
    66: "light freezing rain",
    67: "heavy freezing rain",
    71: "slight snow",
    73: "moderate snow",
    75: "heavy snow",
    77: "snow grains",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    85: "slight snow showers",
    86: "heavy snow showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail",
}


def _normalize_region_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_only.lower().split()).strip()


REGION_INDEX: dict[str, WeatherRegionProfile] = {}
for profile in REGION_PROFILES:
    REGION_INDEX[_normalize_region_key(profile.name)] = profile
    for alias in profile.aliases:
        REGION_INDEX[_normalize_region_key(alias)] = profile


class WeatherService:
    BASE_URL = "https://api.open-meteo.com/v1/forecast"
    CURRENT_FIELDS = ",".join(
        (
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "wind_speed_10m",
            "weather_code",
        )
    )
    DAILY_FIELDS = ",".join(
        (
            "temperature_2m_mean",
            "relative_humidity_2m_mean",
            "precipitation_sum",
            "wind_speed_10m_max",
            "precipitation_probability_max",
            "weather_code",
        )
    )

    def __init__(self) -> None:
        self._circuit_breaker_tripped = False
        self._circuit_breaker_reset_at = 0.0
        self._dlq = DeadLetterQueue()

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError)),
    )
    async def _fetch_openmeteo_raw(self, profile: WeatherRegionProfile, forecast_days: int) -> dict:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(
                self.BASE_URL,
                params={
                    "latitude": profile.lat,
                    "longitude": profile.lon,
                    "current": self.CURRENT_FIELDS,
                    "daily": self.DAILY_FIELDS,
                    "forecast_days": forecast_days,
                    "timezone": "auto",
                    "wind_speed_unit": "ms",
                    "temperature_unit": "celsius",
                    "precipitation_unit": "mm",
                },
            )
            response.raise_for_status()
            return response.json()

    def supported_regions(self) -> list[str]:
        return [profile.name for profile in REGION_PROFILES]

    def _resolve_region_profile(
        self,
        region: str,
        lat: float | None = None,
        lon: float | None = None,
    ) -> WeatherRegionProfile:
        if lat is not None and lon is not None:
            return WeatherRegionProfile(name=region or "custom", country="custom", lat=lat, lon=lon)

        profile = REGION_INDEX.get(_normalize_region_key(region))
        if profile is not None:
            return profile
        return REGION_INDEX["minas gerais"]

    def _risk_level(self, score: float) -> str:
        if score >= 0.75:
            return "high"
        if score >= 0.45:
            return "moderate"
        if score >= 0.2:
            return "low"
        return "minimal"

    async def get_snapshot(
        self,
        region: str,
        days: int = 7,
        lat: float | None = None,
        lon: float | None = None,
    ) -> WeatherSnapshot:
        profile = self._resolve_region_profile(region, lat, lon)
        live_snapshot = await self._live_snapshot(profile, days)
        if live_snapshot is not None:
            return live_snapshot
        return self._demo_snapshot(profile, days)

    async def get_current(
        self,
        region: str,
        lat: float | None = None,
        lon: float | None = None,
    ) -> WeatherCurrentResponse:
        snapshot = await self.get_snapshot(region=region, days=settings.weather_forecast_days, lat=lat, lon=lon)
        return snapshot.current

    async def get_forecast(self, region: str, days: int = 7) -> WeatherForecastResponse:
        snapshot = await self.get_snapshot(region=region, days=days)
        return snapshot.forecast

    async def get_risk_assessment(self, region: str) -> RiskAssessmentResponse:
        forecast = await self.get_forecast(region, days=5)
        avg_humidity = sum(point.humidity_pct for point in forecast.forecast) / len(forecast.forecast)
        avg_rainfall = sum(point.rainfall_mm for point in forecast.forecast) / len(forecast.forecast)
        min_temp = min(point.temp_c for point in forecast.forecast)
        avg_wind = sum(point.wind_speed_ms for point in forecast.forecast) / len(forecast.forecast)

        rust_score = min(0.95, 0.10 + (avg_humidity / 100.0) * 0.65 + min(avg_rainfall, 14.0) / 32.0)
        berry_score = min(0.9, 0.08 + (avg_rainfall / 18.0) + (avg_humidity / 240.0))
        drought_score = max(0.05, 0.72 - (avg_rainfall / 16.0))
        frost_score = 0.65 if min_temp <= 4 else 0.05
        wind_disruption_score = min(0.8, max(0.05, avg_wind / 18.0))

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
            RiskSignal(
                name="wind_disruption",
                level=self._risk_level(wind_disruption_score),
                score=round(wind_disruption_score, 2),
                trigger=f"avg wind {avg_wind:.1f} m/s",
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

    async def _live_snapshot(self, profile: WeatherRegionProfile, days: int) -> WeatherSnapshot | None:
        forecast_days = max(1, min(days, 14))

        # Software Circuit Breaker Check
        now = perf_counter()
        if self._circuit_breaker_tripped:
            if now > self._circuit_breaker_reset_at:
                logger.info("WeatherService: Circuit breaker attempting reset.")
                self._circuit_breaker_tripped = False
            else:
                logger.debug("WeatherService: Circuit breaker active, bypassing remote node for {}", profile.name)
                return None

        try:
            payload = await self._fetch_openmeteo_raw(profile, forecast_days)
        except Exception as exc:
            logger.warning("Open-Meteo failed repeatedly for {}: {} | Tripping circuit breaker", profile.name, exc)
            self._circuit_breaker_tripped = True
            self._circuit_breaker_reset_at = perf_counter() + 60.0  # Cool down for 60 seconds

            # Push structured failure to Dead Letter Queue
            await self._dlq.push(
                event_type="openmeteo_fetch_error",
                payload={"region": profile.name, "lat": profile.lat, "lon": profile.lon},
                error_message=str(exc),
            )
            return None

        current_payload = payload.get("current") or {}
        daily_payload = payload.get("daily") or {}
        if not current_payload or not daily_payload:
            logger.warning("Open-Meteo returned incomplete payload for {}", profile.name)
            return None

        current = WeatherCurrentResponse(
            region=profile.name,
            lat=float(payload.get("latitude", profile.lat)),
            lon=float(payload.get("longitude", profile.lon)),
            temperature_c=self._coerce_float(current_payload.get("temperature_2m")),
            humidity_pct=self._coerce_float(current_payload.get("relative_humidity_2m")),
            rainfall_mm=self._coerce_float(current_payload.get("precipitation")),
            wind_speed_ms=self._coerce_float(current_payload.get("wind_speed_10m")),
            description=self._weather_code_description(current_payload.get("weather_code")),
            timestamp=self._parse_payload_datetime(current_payload.get("time"), payload.get("utc_offset_seconds")),
            service_mode="live_open_meteo",
        )

        forecast_points: list[WeatherForecastPoint] = []
        daily_dates = list(daily_payload.get("time") or [])
        for index, day_key in enumerate(daily_dates[:forecast_days], start=1):
            forecast_points.append(
                WeatherForecastPoint(
                    day=index,
                    date=str(day_key),
                    temp_c=self._series_value(daily_payload, "temperature_2m_mean", index - 1),
                    humidity_pct=self._series_value(daily_payload, "relative_humidity_2m_mean", index - 1),
                    rainfall_mm=self._series_value(daily_payload, "precipitation_sum", index - 1),
                    wind_speed_ms=self._series_value(daily_payload, "wind_speed_10m_max", index - 1),
                    precipitation_probability_pct=self._series_value(
                        daily_payload,
                        "precipitation_probability_max",
                        index - 1,
                    ),
                )
            )

        forecast = WeatherForecastResponse(
            region=profile.name,
            days=len(forecast_points),
            forecast=forecast_points,
            service_mode="live_open_meteo",
        )
        return WeatherSnapshot(profile=profile, current=current, forecast=forecast)

    def _demo_snapshot(self, profile: WeatherRegionProfile, days: int) -> WeatherSnapshot:
        forecast_days = max(1, min(days, 14))
        now = datetime.now(timezone.utc)
        current = WeatherCurrentResponse(
            region=profile.name,
            lat=profile.lat,
            lon=profile.lon,
            temperature_c=20.4,
            humidity_pct=78.0,
            rainfall_mm=2.8,
            wind_speed_ms=3.1,
            description="partly cloudy",
            timestamp=now,
            service_mode="demo_open_meteo_profile",
        )
        forecast = WeatherForecastResponse(
            region=profile.name,
            days=forecast_days,
            forecast=[
                WeatherForecastPoint(
                    day=index + 1,
                    date=(now + timedelta(days=index + 1)).date().isoformat(),
                    temp_c=round(19.6 + (index * 0.35), 1),
                    humidity_pct=round(80.0 - min(index * 1.2, 8.0), 1),
                    rainfall_mm=round(max(0.7, 6.2 - (index * 0.45)), 1),
                    wind_speed_ms=round(3.2 + (index * 0.15), 1),
                    precipitation_probability_pct=round(max(18.0, 72.0 - (index * 6.0)), 1),
                )
                for index in range(forecast_days)
            ],
            service_mode="demo_open_meteo_profile",
        )
        return WeatherSnapshot(profile=profile, current=current, forecast=forecast)

    def _parse_payload_datetime(self, value, utc_offset_seconds) -> datetime:
        text = str(value or "").strip()
        if not text:
            return datetime.now(timezone.utc)

        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is not None:
                return parsed
            offset = int(utc_offset_seconds or 0)
            return parsed.replace(tzinfo=timezone(timedelta(seconds=offset)))
        except (TypeError, ValueError):
            return datetime.now(timezone.utc)

    def _series_value(self, payload: dict, key: str, index: int) -> float:
        series = payload.get(key) or []
        if index >= len(series):
            return 0.0
        return self._coerce_float(series[index])

    def _weather_code_description(self, value) -> str:
        try:
            return WMO_CODE_DESCRIPTIONS.get(int(value), "unclassified weather")
        except (TypeError, ValueError):
            return "unclassified weather"

    def _coerce_float(self, value) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
