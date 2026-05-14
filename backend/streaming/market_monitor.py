"""
streaming/market_monitor.py
============================
STEP 4 — Market Monitor Loop (live intelligence heartbeat)

Loop:
    while True:
        read live prices from Redis
        detect spikes
        detect volatility regime
        generate alerts
        update risk score
        sleep

This is the autonomous heartbeat that keeps market state current
without requiring user queries.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from core.logger import logger
from core.config import settings
from streaming.redis_cache import RedisMarketCache

# ─── Thresholds ────────────────────────────────────────────────────────────
# Fix #11: removed MONITOR_INTERVAL module constant — use settings.monitor_interval_seconds
SPIKE_ALERT_PCT: float  = 2.0     # % change triggers spike alert
HIGH_VOL_PCT: float     = 2.5     # % volatility triggers high-vol alert
RISK_HIGH_THRESHOLD     = 70.0    # risk score 0-100

# ─── Risk score weights ────────────────────────────────────────────────────
WEIGHT_CHANGE_PCT    = 0.40
WEIGHT_VOLATILITY    = 0.40
WEIGHT_ALERT_COUNT   = 0.20


class MarketMonitor:
    """
    Autonomous market monitor — reads Redis hot cache, evaluates signals,
    writes risk scores and alerts back to Redis.

    Start as an asyncio.Task via  start().
    """

    def __init__(self, cache: RedisMarketCache | None = None) -> None:
        self._cache   = cache or RedisMarketCache()
        self._running = False
        self._last_arabica_price: float | None = None
        self._last_robusta_price: float | None = None

    async def start(self) -> None:
        self._running = True
        logger.info("MarketMonitor started (interval={}s)", settings.monitor_interval_seconds)
        while self._running:
            try:
                await self._monitor_tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("MarketMonitor tick error: {}", exc)
            await asyncio.sleep(settings.monitor_interval_seconds)

    async def stop(self) -> None:
        self._running = False

    # ─── Core tick ───────────────────────────────────────────────────────────

    async def _monitor_tick(self) -> None:
        snapshot = await self._cache.get_live_snapshot()
        arabica  = snapshot.get("arabica") or {}
        robusta  = snapshot.get("robusta") or {}
        vol      = snapshot.get("volatility") or {}
        alerts   = snapshot.get("recent_alerts") or []

        a_price   = float(arabica.get("arabica_price") or 0)
        r_price   = float(robusta.get("robusta_price") or 0)
        a_change  = float(arabica.get("change_percent") or 0)
        r_change  = float(robusta.get("change_percent") or 0)
        a_vol     = float(vol.get("arabica_volatility_pct") or 0)
        r_vol     = float(vol.get("robusta_volatility_pct") or 0)

        # ── Spike detection ──────────────────────────────────────────────────
        for market, change, price, currency in [
            ("arabica", a_change, a_price, "US cents/lb"),
            ("robusta",  r_change, r_price, "USD/tonne"),
        ]:
            if abs(change) >= SPIKE_ALERT_PCT and price > 0:
                alert = {
                    "type": "price_spike",
                    "market": market,
                    "price": price,
                    "change_percent": change,
                    "currency": currency,
                    "severity": "high" if abs(change) >= 4.0 else "medium",
                    "message": (
                        f"⚡ {market.title()} spike: {change:+.2f}% "
                        f"at {price} {currency}"
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                await self._cache.push_alert(alert)
                logger.info("MarketMonitor spike alert | {}", alert["message"])

        # ── Volatility regime alert ──────────────────────────────────────────
        for market, v in [("arabica", a_vol), ("robusta", r_vol)]:
            if v >= HIGH_VOL_PCT:
                await self._cache.push_alert({
                    "type": "high_volatility",
                    "market": market,
                    "volatility_pct": v,
                    "severity": "medium",
                    "message": f"📊 {market.title()} volatility elevated: {v:.2f}%",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

        # ── Risk score ───────────────────────────────────────────────────────
        risk_score = self._compute_risk(a_change, r_change, a_vol, r_vol, len(alerts))
        risk_level = (
            "high"   if risk_score >= RISK_HIGH_THRESHOLD
            else "medium" if risk_score >= 40
            else "low"
        )
        risk_state = {
            "risk_score": risk_score,
            "risk_level": risk_level,
            "drivers": {
                "arabica_change_pct": a_change,
                "robusta_change_pct": r_change,
                "arabica_volatility": a_vol,
                "robusta_volatility": r_vol,
                "active_alert_count": len(alerts),
            },
            "recommendation": self._build_recommendation(risk_level, a_change, r_change),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._cache.set_json("coffee:live:risk", risk_state, ttl=120)

        if risk_score >= RISK_HIGH_THRESHOLD:
            await self._cache.push_alert({
                "type": "risk_elevated",
                "risk_score": risk_score,
                "risk_level": risk_level,
                "severity": "high",
                "message": (
                    f"🔴 Market risk elevated (score={risk_score:.0f}/100). "
                    "Consider delaying bulk transactions."
                ),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        logger.debug(
            "MarketMonitor | risk={:.0f} ({}) arabica={:.2f}% robusta={:.2f}%",
            risk_score, risk_level, a_change, r_change,
        )

    # ─── Risk computation ────────────────────────────────────────────────────

    def _compute_risk(
        self,
        a_change: float,
        r_change: float,
        a_vol: float,
        r_vol: float,
        alert_count: int,
    ) -> float:
        avg_change = (abs(a_change) + abs(r_change)) / 2
        avg_vol    = (a_vol + r_vol) / 2
        capped_alerts = min(alert_count / 5, 1.0)   # normalise 0-1

        score = (
            WEIGHT_CHANGE_PCT  * min(avg_change / 5.0, 1.0) * 100
            + WEIGHT_VOLATILITY * min(avg_vol / 5.0, 1.0)   * 100
            + WEIGHT_ALERT_COUNT * capped_alerts              * 100
        )
        return round(min(score, 100.0), 1)

    def _build_recommendation(self, risk_level: str, a_change: float, r_change: float) -> str:
        if risk_level == "high":
            return (
                "Market risk remains elevated. Farmers and traders may benefit from "
                "delaying bulk sales if volatility continues over the next 48 hours."
            )
        if risk_level == "medium":
            avg = (a_change + r_change) / 2
            direction = "upward" if avg > 0 else "downward"
            return (
                f"Moderate {direction} pressure detected. Monitor positions closely "
                "and consider hedging against further moves."
            )
        return (
            "Market conditions appear stable. Standard trading activity remains appropriate."
        )
