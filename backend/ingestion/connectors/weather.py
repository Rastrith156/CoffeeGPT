from __future__ import annotations

from core.config import settings
from .base import BaseConnector

class WeatherConnector(BaseConnector):
    name = "weather"
    description = "Growing region weather observations"

    def __init__(self, weather_service, regions: list[str]) -> None:
        self.weather_service = weather_service
        self.regions = regions

    async def fetch(self) -> list[dict]:
        records = []
        for region in self.regions:
            snapshot = await self.weather_service.get_snapshot(region=region, days=settings.weather_forecast_days)
            current = snapshot.current
            forecast = snapshot.forecast
            profile = snapshot.profile
            current_timestamp = current.timestamp.isoformat()
            snapshot_date = current.timestamp.date().isoformat()
            region_key = self._region_key(profile.name)

            records.append(
                self._record(
                    title=f"{profile.name} current weather",
                    content=(
                        f"{profile.name} current coffee weather: temperature {current.temperature_c} C, "
                        f"humidity {current.humidity_pct}%, precipitation {current.rainfall_mm} mm, "
                        f"wind {current.wind_speed_ms} m/s, conditions {current.description}. "
                        f"Observed at {current_timestamp}."
                    ),
                    record_type="weather_current",
                    raw={
                        "region": profile.name,
                        "country": profile.country,
                        "lat": current.lat,
                        "lon": current.lon,
                        "current": current.model_dump(mode="json"),
                        "service_mode": current.service_mode,
                    },
                    metadata={
                        "source": self.name,
                        "title": f"{profile.name} current weather",
                        "document_id": f"weather_current::{region_key}::{snapshot_date}",
                        "region": profile.name,
                        "country": profile.country,
                        "published_at": current_timestamp,
                        "snapshot_date": snapshot_date,
                        "lat": current.lat,
                        "lon": current.lon,
                    },
                )
            )

            forecast_lines = []
            for point in forecast.forecast[:3]:
                forecast_lines.append(
                    f"{point.date}: rain {point.rainfall_mm} mm, humidity {point.humidity_pct}%, "
                    f"temp {point.temp_c} C, wind {point.wind_speed_ms} m/s, precip probability "
                    f"{point.precipitation_probability_pct}%"
                )

            records.append(
                self._record(
                    title=f"{profile.name} weather outlook",
                    content=(
                        f"{profile.name} {forecast.days}-day coffee weather outlook. "
                        f"Current conditions remain {current.description} with humidity {current.humidity_pct}% and "
                        f"precipitation {current.rainfall_mm} mm. "
                        f"Near-term forecast: {'; '.join(forecast_lines)}."
                    ),
                    record_type="weather_forecast",
                    raw={
                        "region": profile.name,
                        "country": profile.country,
                        "lat": current.lat,
                        "lon": current.lon,
                        "current": current.model_dump(mode="json"),
                        "forecast": [point.model_dump(mode="json") for point in forecast.forecast],
                        "service_mode": forecast.service_mode,
                    },
                    metadata={
                        "source": self.name,
                        "title": f"{profile.name} weather outlook",
                        "document_id": f"weather_forecast::{region_key}::{snapshot_date}",
                        "region": profile.name,
                        "country": profile.country,
                        "published_at": current_timestamp,
                        "snapshot_date": snapshot_date,
                        "lat": current.lat,
                        "lon": current.lon,
                    },
                )
            )
        return records

    def _region_key(self, region: str) -> str:
        return region.lower().replace(" ", "_").replace("-", "_")
