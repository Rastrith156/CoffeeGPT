"""
agents/alert_agent.py
=====================
Specialized Agent — Anomaly detection and active alerts.

Reads active alerts from Redis and summarizes them
into a structured alert intelligence report.
"""
from __future__ import annotations

from datetime import datetime, timezone
from collections import Counter

from streaming.redis_cache import RedisMarketCache


class AlertAgent:
    """Alert intelligence agent."""

    def __init__(self, cache: RedisMarketCache | None = None) -> None:
        self._cache = cache or RedisMarketCache()

    async def analyze(self, question: str = "") -> dict:
        alerts   = await self._cache.get_alerts(20)
        spike    = await self._cache.get_latest_spike()

        type_counts = Counter(a.get("type", "unknown") for a in alerts)
        severity_counts = Counter(a.get("severity", "unknown") for a in alerts)

        high_alerts = [a for a in alerts if a.get("severity") == "high"]
        most_recent = alerts[0] if alerts else None

        return {
            "agent": "alert",
            "total_alerts": len(alerts),
            "by_type": dict(type_counts),
            "by_severity": dict(severity_counts),
            "latest_spike": spike,
            "most_recent_alert": most_recent,
            "high_severity_alerts": high_alerts[:5],
            "summary": self._build_summary(alerts, spike, high_alerts),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _build_summary(
        self, alerts: list, spike: dict | None, high_alerts: list
    ) -> str:
        if not alerts:
            return "No active market alerts detected in the current monitoring window."
        parts = [f"{len(alerts)} market alert(s) active."]
        if spike:
            parts.append(spike.get("message", "Price spike detected."))
        if high_alerts:
            parts.append(
                f"{len(high_alerts)} high-severity alert(s) require immediate attention."
            )
        return " ".join(parts)
