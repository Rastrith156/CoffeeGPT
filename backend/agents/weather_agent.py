"""
agents/weather_agent.py
========================
Fix #20 — WeatherAgent: reads live weather data from WeatherService
and Redis cache to produce a concise market-impact summary.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from core.config import settings
from core.logger import logger


class WeatherAgent:
    """
    Specialized agent for weather-driven market impact analysis.
    Reads from WeatherService (Open-Meteo) and the Redis hot cache.
    """

    def __init__(
        self,
        cache=None,
        weather_service=None,
    ) -> None:
        # Import lazily to avoid circular imports at module load time
        if cache is None:
            try:
                from streaming.redis_cache import RedisMarketCache
                cache = RedisMarketCache()
            except ImportError:
                cache = None
        self._cache = cache
        self._weather_service = weather_service

    async def analyze(self, question: str = "") -> dict[str, Any]:
        """
        Return a concise weather intelligence summary.
        Checks Redis for cached risk data first, then falls back to WeatherService.
        """
        summary_lines: list[str] = []

        # 1. Try Redis hot cache for pre-computed weather/risk state
        if self._cache is not None:
            try:
                risk = await self._cache.get_json("coffee:live:risk") or {}
                if risk.get("risk_level"):
                    summary_lines.append(
                        f"Current market risk: {risk['risk_level']} "
                        f"(score {risk.get('risk_score', 0):.0f}/100)."
                    )
            except Exception as exc:
                logger.debug("WeatherAgent: Redis risk read failed: {}", exc)

        # 2. Pull live weather for key regions from WeatherService
        if self._weather_service is not None:
            # Detect region from question if mentioned
            question_lower = question.lower()
            target_regions = [
                r for r in settings.weather_regions
                if r.lower() in question_lower
            ] or settings.weather_regions[:3]  # default to first 3 regions

            for region in target_regions[:2]:   # cap at 2 to avoid latency
                try:
                    risk_report = await self._weather_service.get_risk_assessment(region)
                    top_risk = max(risk_report.risks, key=lambda r: r.score, default=None)
                    if top_risk and top_risk.score > 0.3:
                        summary_lines.append(
                            f"{region}: {top_risk.name.replace('_', ' ')} risk "
                            f"{top_risk.level} (score {top_risk.score:.2f}) — {top_risk.trigger}."
                        )
                except Exception as exc:
                    logger.debug("WeatherAgent: weather fetch failed for {}: {}", region, exc)

        summary = " ".join(summary_lines) if summary_lines else (
            "No live weather intelligence available at this time."
        )

        return {
            "agent": "weather",
            "summary": summary,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }
