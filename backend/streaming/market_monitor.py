"""
streaming/market_monitor.py
============================
STEP 4 — Market Monitor Loop (live intelligence heartbeat)

Loop:
    while True:
        read live prices from Redis
        detect spikes (with deduplication)
        detect volatility regime
        generate alerts
        update risk score
        sleep

This is the autonomous heartbeat that keeps market state current
without requiring user queries.

Fixes applied:
  - _run_tick() alias added so tests that call monitor._run_tick() work correctly
  - Spike detection reads BOTH "change_pct" and "change_percent" keys (supports
    live-fetch dict AND Redis snapshot dict)
  - Alert deduplication: only fire a new spike alert when the current change_pct
    differs from the last-alerted change_pct by >= 0.5%, preventing alert floods
  - Redis reconnect: cache._get_client() is called each tick so a recovered Redis
    connection is picked up automatically
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from core.logger import logger
from core.config import settings
from streaming.redis_cache import RedisMarketCache

# ─── Thresholds ────────────────────────────────────────────────────────────
SPIKE_ALERT_PCT: float = settings.spike_threshold_pct        # default 2.0%
HIGH_VOL_PCT: float    = settings.high_volatility_threshold_pct  # default 2.5%
RISK_HIGH_THRESHOLD    = 70.0   # risk score 0-100
DEDUP_MIN_DELTA        = 0.5    # min pct change to fire a new alert for same commodity

# ─── Risk score weights ────────────────────────────────────────────────────
WEIGHT_CHANGE_PCT  = 0.40
WEIGHT_VOLATILITY  = 0.40
WEIGHT_ALERT_COUNT = 0.20


def _extract_price_change(tick: dict[str, Any]) -> tuple[float, float]:
    """
    Extract (price, change_pct) from a tick dict.

    Accepts two key conventions:
      • Live fetch:  {"price": x, "change_pct": y}
      • Redis cache: {"arabica_price": x, "change_percent": y}
                  or {"robusta_price": x, "change_percent": y}
    Returns (0.0, 0.0) when both values are absent.
    """
    price = float(
        tick.get("price")
        or tick.get("arabica_price")
        or tick.get("robusta_price")
        or 0
    )
    change = float(
        tick.get("change_pct")
        or tick.get("change_percent")
        or 0
    )
    return price, change


class MarketMonitor:
    """
    Autonomous market monitor — reads Redis hot cache, evaluates signals,
    writes risk scores and alerts back to Redis.

    Start as an asyncio.Task via  start().
    """

    def __init__(self, cache: RedisMarketCache | None = None) -> None:
        self._cache   = cache or RedisMarketCache()
        self._running = False
        # Deduplication state: last change_pct for which we fired a spike alert
        self._last_alert_pct: dict[str, float] = {}

    async def start(self) -> None:
        self._running = True
        logger.info("MarketMonitor started (interval={}s)", settings.monitor_interval_seconds)
        while self._running:
            try:
                await self._run_tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning("MarketMonitor tick error: {}", exc)
            await asyncio.sleep(settings.monitor_interval_seconds)

    async def stop(self) -> None:
        self._running = False

    # ─── Public tick (tests call this directly) ──────────────────────────────

    async def _run_tick(self) -> None:
        """
        Primary tick entry-point.  Tests call _run_tick() directly.
        Internally routes to _execute_tick() for the full monitoring logic.
        """
        await self._execute_tick()

    # Legacy alias kept for any code that references the old name
    _monitor_tick = _run_tick  # type: ignore[assignment]

    # ─── Core logic ──────────────────────────────────────────────────────────

    async def _execute_tick(self) -> None:
        """
        Full tick execution:
          1. Read live prices (from _fetch_live_prices or Redis snapshot)
          2. Detect spikes with deduplication
          3. Detect high-volatility regime
          4. Compute & persist risk score
        """
        live = await self._fetch_live_prices()

        arabica_tick = live.get("arabica") or {}
        robusta_tick = live.get("robusta") or {}

        a_price, a_change = _extract_price_change(arabica_tick) if arabica_tick else (0.0, 0.0)
        r_price, r_change = _extract_price_change(robusta_tick) if robusta_tick else (0.0, 0.0)

        # Also fetch volatility from the hot-cache snapshot (not in live fetch)
        snapshot = await self._cache.get_live_snapshot()
        vol      = snapshot.get("volatility") or {}
        alerts   = snapshot.get("recent_alerts") or []
        a_vol    = float(vol.get("arabica_volatility_pct") or 0)
        r_vol    = float(vol.get("robusta_volatility_pct") or 0)

        # ── Spike detection ──────────────────────────────────────────────────
        for market, change, price, currency in [
            ("arabica", a_change, a_price, "US cents/lb"),
            ("robusta",  r_change, r_price, "USD/tonne"),
        ]:
            if abs(change) >= SPIKE_ALERT_PCT and price > 0:
                # Deduplication: skip if we already alerted for a very similar move
                last = self._last_alert_pct.get(market, 0.0)
                if abs(abs(change) - abs(last)) >= DEDUP_MIN_DELTA:
                    severity = "high" if abs(change) >= 4.0 else "medium"
                    alert: dict[str, Any] = {
                        "type":          "price_spike",
                        "commodity":     market,   # tests assert "commodity"
                        "market":        market,
                        "price":         price,
                        "change_pct":    change,   # tests assert "change_pct"
                        "change_percent": change,
                        "currency":      currency,
                        "severity":      severity.upper(),  # tests compare .upper()
                        "message": (
                            f"⚡ {market.title()} spike: {change:+.2f}% "
                            f"at {price} {currency}"
                        ),
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    try:
                        await self._cache.push_alert(alert)
                        await self._cache.push_spike(alert)
                        self._last_alert_pct[market] = change
                        logger.info("MarketMonitor spike alert | {}", alert["message"])
                    except Exception as exc:
                        logger.warning("MarketMonitor: failed to push alert: {}", exc)

        # ── Volatility regime alert ──────────────────────────────────────────
        for market, v in [("arabica", a_vol), ("robusta", r_vol)]:
            if v >= HIGH_VOL_PCT:
                try:
                    await self._cache.push_alert({
                        "type":          "high_volatility",
                        "commodity":     market,
                        "market":        market,
                        "volatility_pct": v,
                        "change_pct":    v,
                        "severity":      "MEDIUM",
                        "message": f"📊 {market.title()} volatility elevated: {v:.2f}%",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })
                except Exception as exc:
                    logger.warning("MarketMonitor: volatility alert push failed: {}", exc)

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
                "arabica_change_pct":  a_change,
                "robusta_change_pct":  r_change,
                "arabica_volatility":  a_vol,
                "robusta_volatility":  r_vol,
                "active_alert_count":  len(alerts),
            },
            "recommendation": self._build_recommendation(risk_level, a_change, r_change),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self._cache.set_json("coffee:live:risk", risk_state, ttl=120)

            if risk_score >= RISK_HIGH_THRESHOLD:
                await self._cache.push_alert({
                    "type":       "risk_elevated",
                    "risk_score": risk_score,
                    "risk_level": risk_level,
                    "severity":   "HIGH",
                    "message": (
                        f"🔴 Market risk elevated (score={risk_score:.0f}/100). "
                        "Consider delaying bulk transactions."
                    ),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })
        except Exception as exc:
            logger.warning("MarketMonitor: risk state push failed: {}", exc)

        logger.debug(
            "MarketMonitor | risk={:.0f} ({}) arabica={:.2f}% robusta={:.2f}%",
            risk_score, risk_level, a_change, r_change,
        )

    # ─── Live price fetch (can be monkey-patched in tests) ───────────────────

    async def _fetch_live_prices(self) -> dict[str, Any]:
        """
        Fetch the latest prices from the Redis hot cache.
        Returns dict with keys "arabica" and "robusta", each being a price tick
        dict using the live convention: {"price": x, "change_pct": y}
        or None if unavailable.

        Tests patch this method to inject controlled price ticks.
        """
        arabica_raw = await self._cache.get_arabica()
        robusta_raw = await self._cache.get_robusta()

        def _normalise(raw: dict[str, Any] | None, price_key: str) -> dict[str, Any] | None:
            if not raw:
                return None
            return {
                "price":      float(raw.get(price_key) or 0),
                "change_pct": float(raw.get("change_percent") or raw.get("change_pct") or 0),
            }

        return {
            "arabica": _normalise(arabica_raw, "arabica_price"),
            "robusta":  _normalise(robusta_raw, "robusta_price"),
        }

    # ─── Risk computation ────────────────────────────────────────────────────

    def _compute_risk(
        self,
        a_change: float,
        r_change: float,
        a_vol: float,
        r_vol: float,
        alert_count: int,
    ) -> float:
        avg_change   = (abs(a_change) + abs(r_change)) / 2
        avg_vol      = (a_vol + r_vol) / 2
        capped_alerts = min(alert_count / 5, 1.0)  # normalise 0-1

        score = (
            WEIGHT_CHANGE_PCT   * min(avg_change / 5.0, 1.0) * 100
            + WEIGHT_VOLATILITY * min(avg_vol / 5.0, 1.0)    * 100
            + WEIGHT_ALERT_COUNT * capped_alerts               * 100
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
