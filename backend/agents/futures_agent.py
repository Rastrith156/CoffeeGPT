"""
agents/futures_agent.py
=======================
Specialized Agent — Futures market movement intelligence.

Reads from:
  1. Redis HOT LAYER (live prices, spikes)
  2. Market service (historical snapshots)

Returns a structured FuturesIntelligence object for the orchestrator.
"""
from __future__ import annotations

from datetime import datetime, timezone

from streaming.redis_cache import RedisMarketCache


class FuturesAgent:
    """Futures intelligence agent — live + historical synthesis."""

    def __init__(
        self,
        cache: RedisMarketCache | None = None,
        market_service=None,
    ) -> None:
        self._cache          = cache or RedisMarketCache()
        self._market_service = market_service

    async def analyze(self, question: str = "") -> dict:
        """
        Returns a structured futures intelligence snapshot.
        Hot-layer data takes priority for recency; historical data
        provides context depth.
        """
        live_state = await self._cache.get_live_snapshot()
        arabica    = live_state.get("arabica") or {}
        robusta    = live_state.get("robusta") or {}
        spike      = live_state.get("latest_spike")
        risk       = await self._cache.get_json("coffee:live:risk")

        a_price   = float(arabica.get("arabica_price") or 0)
        r_price   = float(robusta.get("robusta_price") or 0)
        a_change  = float(arabica.get("change_percent") or 0)
        r_change  = float(robusta.get("change_percent") or 0)

        has_live  = a_price > 0 or r_price > 0

        analysis = {
            "agent": "futures",
            "has_live_data": has_live,
            "arabica": {
                "price": a_price,
                "change_percent": a_change,
                "currency": "US cents/lb",
                "updated_at": arabica.get("updated_at"),
                "source": arabica.get("source", "unknown"),
            },
            "robusta": {
                "price": r_price,
                "change_percent": r_change,
                "currency": "USD/tonne",
                "updated_at": robusta.get("updated_at"),
                "source": robusta.get("source", "unknown"),
            },
            "spike": spike,
            "risk": risk,
            "summary": self._build_summary(
                a_price, r_price, a_change, r_change, spike, risk
            ),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
        }
        return analysis

    def _build_summary(
        self,
        a_price: float,
        r_price: float,
        a_change: float,
        r_change: float,
        spike: dict | None,
        risk: dict | None,
    ) -> str:
        parts = []
        if a_price > 0:
            parts.append(
                f"Arabica futures at {a_price:.2f} US cents/lb ({a_change:+.2f}%)."
            )
        if r_price > 0:
            parts.append(
                f"Robusta at {r_price:.0f} USD/tonne ({r_change:+.2f}%)."
            )
        if spike:
            parts.append(
                f"Recent spike: {spike.get('message', 'price spike detected')}."
            )
        if risk:
            parts.append(
                f"Market risk: {risk.get('risk_level', 'unknown')} "
                f"(score {risk.get('risk_score', 0):.0f}/100)."
            )
        if not parts:
            return "Live futures data is not currently available."
        return " ".join(parts)
