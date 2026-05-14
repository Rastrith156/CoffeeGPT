"""
agents/risk_agent.py
====================
Specialized Agent — Volatility / Risk intelligence.

Reads risk scores from Redis and synthesizes
a structured risk assessment for the orchestrator.
"""
from __future__ import annotations

from datetime import datetime, timezone

from streaming.redis_cache import RedisMarketCache


class RiskAgent:
    """Risk intelligence agent."""

    def __init__(self, cache: RedisMarketCache | None = None) -> None:
        self._cache = cache or RedisMarketCache()

    async def analyze(self, question: str = "") -> dict:
        risk      = await self._cache.get_json("coffee:live:risk") or {}
        vol       = await self._cache.get_volatility() or {}
        alerts    = await self._cache.get_alerts(10)

        risk_level = risk.get("risk_level", "unknown")
        risk_score = float(risk.get("risk_score") or 0)
        drivers    = risk.get("drivers", {})
        recommendation = risk.get("recommendation", "")

        spike_alerts = [a for a in alerts if a.get("type") == "price_spike"]
        vol_alerts   = [a for a in alerts if a.get("type") == "high_volatility"]

        return {
            "agent": "risk",
            "risk_level": risk_level,
            "risk_score": risk_score,
            "drivers": drivers,
            "recommendation": recommendation,
            "volatility": {
                "arabica_pct": float(vol.get("arabica_volatility_pct") or 0),
                "robusta_pct": float(vol.get("robusta_volatility_pct") or 0),
            },
            "active_spike_alerts": len(spike_alerts),
            "active_vol_alerts": len(vol_alerts),
            "summary": self._build_summary(risk_level, risk_score, recommendation, spike_alerts),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _build_summary(
        self, risk_level: str, risk_score: float, recommendation: str, spike_alerts: list
    ) -> str:
        parts = [
            f"Current market risk: {risk_level} (score {risk_score:.0f}/100)."
        ]
        if spike_alerts:
            parts.append(
                f"{len(spike_alerts)} active price spike alert(s) detected."
            )
        if recommendation:
            parts.append(recommendation)
        return " ".join(parts)
