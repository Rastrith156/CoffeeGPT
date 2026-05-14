"""
agents/forecast_agent.py
========================
Specialized Agent — Trend projection / Forecast intelligence.

Reads historical patterns and current live signals to
generate a near-term directional outlook.
"""
from __future__ import annotations

from datetime import datetime, timezone

from streaming.redis_cache import RedisMarketCache


class ForecastAgent:
    """Forecast intelligence agent — trend projection."""

    def __init__(
        self,
        cache: RedisMarketCache | None = None,
        forecast_service=None,
    ) -> None:
        self._cache            = cache or RedisMarketCache()
        self._forecast_service = forecast_service

    async def analyze(self, question: str = "") -> dict:
        arabica  = await self._cache.get_arabica() or {}
        robusta  = await self._cache.get_robusta() or {}
        risk     = await self._cache.get_json("coffee:live:risk") or {}

        a_change  = float(arabica.get("change_percent") or 0)
        r_change  = float(robusta.get("change_percent") or 0)
        risk_level = risk.get("risk_level", "unknown")

        direction  = self._project_direction(a_change, r_change)
        confidence = self._confidence(a_change, r_change, risk_level)
        outlook    = self._build_outlook(direction, confidence, risk_level, a_change, r_change)

        return {
            "agent": "forecast",
            "direction": direction,
            "confidence": confidence,
            "risk_level": risk_level,
            "arabica_momentum": a_change,
            "robusta_momentum": r_change,
            "outlook": outlook,
            "horizon": "48-72 hours",
            "summary": outlook,
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _project_direction(self, a_change: float, r_change: float) -> str:
        avg = (a_change + r_change) / 2
        if avg >= 1.5:
            return "bullish"
        if avg <= -1.5:
            return "bearish"
        if abs(a_change - r_change) >= 2.0:
            return "diverging"
        return "neutral"

    def _confidence(self, a_change: float, r_change: float, risk_level: str) -> str:
        if risk_level == "high":
            return "low"
        if abs(a_change) >= 2.0 and abs(r_change) >= 2.0:
            return "high"
        if abs(a_change) >= 1.0 or abs(r_change) >= 1.0:
            return "medium"
        return "low"

    def _build_outlook(
        self,
        direction: str,
        confidence: str,
        risk_level: str,
        a_change: float,
        r_change: float,
    ) -> str:
        direction_text = {
            "bullish":   "upward pressure is likely to persist",
            "bearish":   "downward momentum may continue",
            "diverging": "Arabica and Robusta are moving in opposite directions",
            "neutral":   "price action remains indecisive",
        }.get(direction, "trend direction is unclear")

        return (
            f"Over the next 48-72 hours, {direction_text} "
            f"(confidence: {confidence}). "
            f"Arabica momentum: {a_change:+.2f}%, Robusta: {r_change:+.2f}%. "
            f"Market risk is {risk_level}. "
            + (
                "Elevated risk warrants conservative position management."
                if risk_level == "high"
                else "Standard monitoring is recommended."
            )
        )
