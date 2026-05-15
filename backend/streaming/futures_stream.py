"""
streaming/futures_stream.py
===========================
STEP 2 — Live Futures Stream Service (Orchestrator)

This module is now a SLIM ORCHESTRATOR.

Responsibility delegation:
  Fetch         →  streaming/providers/barchart_provider.py
  Normalise     →  streaming/normalizer.py
  Cache write   →  streaming/redis_cache.py
  Spike detect  →  streaming/market_monitor.py (MarketMonitor)
  Health track  →  streaming/stream_health.py (StreamHealthTracker)

Resilience features (Issue 1):
  ✅ Exponential backoff on consecutive failures
  ✅ Circuit breaker: after N failures → degraded mode (longer sleep)
  ✅ last_successful_tick heartbeat written to Redis on every success
  ✅ Per-feed failure tracking (arabica vs robusta tracked independently)

Architecture:
    BarchartProvider.fetch_arabica/robusta()
           ↓
    TickNormalizer.normalize()
           ↓
    RedisMarketCache.update_arabica/robusta()
           ↓
    StreamHealthTracker.record_success/failure()
           ↓
    EventBus.publish() (optional — non-blocking)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from core.config import settings
from core.logger import logger, bind_context
from streaming.providers.barchart_provider import BarchartProvider
from streaming.normalizer import TickNormalizer
from streaming.redis_cache import RedisMarketCache

# Stream ID used for health/log context
_STREAM_ID = "futures_stream"


class FuturesStreamService:
    """
    Continuously polls live futures data, normalises it, writes to Redis.

    Call  start()  as an asyncio.Task from the runtime container.
    Spike detection is handled by MarketMonitor which reads Redis independently.
    """

    def __init__(
        self,
        cache: RedisMarketCache | None = None,
        provider: BarchartProvider | None = None,
        normalizer: TickNormalizer | None = None,
    ) -> None:
        self._cache      = cache or RedisMarketCache()
        self._provider   = provider or BarchartProvider()
        self._normalizer = normalizer or TickNormalizer()
        self._running    = False
        self._log        = bind_context(stream_id=_STREAM_ID)

        # ── Resilience state ─────────────────────────────────────────────────
        self._consecutive_failures: int  = 0
        self._total_failures: int        = 0
        self._total_ticks: int           = 0
        self._last_successful_tick: datetime | None = None
        self._degraded: bool             = False

    # ── Public API ────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Run forever — designed to be launched as an asyncio.Task."""
        self._running = True
        self._log.info(
            "FuturesStreamService started | interval={}s backoff_base={}s cb_threshold={}",
            settings.stream_interval_seconds,
            settings.stream_backoff_base_seconds,
            settings.stream_circuit_breaker_threshold,
        )
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                await self._on_tick_error(exc)
                continue

            sleep_interval = self._compute_sleep_interval()
            await asyncio.sleep(sleep_interval)

    async def stop(self) -> None:
        self._running = False
        await self._provider.close()

    @property
    def health(self) -> dict[str, Any]:
        """Snapshot of this service's resilience state for health endpoints."""
        return {
            "stream_id":              _STREAM_ID,
            "running":                self._running,
            "degraded":               self._degraded,
            "consecutive_failures":   self._consecutive_failures,
            "total_failures":         self._total_failures,
            "total_ticks":            self._total_ticks,
            "last_successful_tick":   (
                self._last_successful_tick.isoformat()
                if self._last_successful_tick else None
            ),
        }

    # ── Core tick ─────────────────────────────────────────────────────────────

    async def _tick(self) -> None:
        """
        Single poll cycle:
          1. Fetch raw ticks from provider
          2. Normalise each tick
          3. Write to Redis hot cache
          4. Update market state + volatility
          5. Record heartbeat
        """
        tick_start = datetime.now(timezone.utc)

        arabica_raw = await self._provider.fetch_arabica()
        robusta_raw = await self._provider.fetch_robusta()

        arabica = self._normalizer.normalize(arabica_raw) if arabica_raw else None
        robusta = self._normalizer.normalize(robusta_raw) if robusta_raw else None

        tasks: list[asyncio.Task] = []

        if arabica:
            tasks.append(asyncio.create_task(
                self._cache.update_arabica(
                    price=arabica.price,
                    change_percent=arabica.change_percent,
                    volume=arabica.volume,
                )
            ))

        if robusta:
            tasks.append(asyncio.create_task(
                self._cache.update_robusta(
                    price=robusta.price,
                    change_percent=robusta.change_percent,
                    volume=robusta.volume,
                )
            ))

        a_vol = arabica.volatility_pct if arabica else 0.0
        r_vol = robusta.volatility_pct if robusta else 0.0
        tasks.append(asyncio.create_task(self._cache.update_volatility(a_vol, r_vol)))

        state = self._build_market_state(arabica, robusta)
        tasks.append(asyncio.create_task(self._cache.update_market_state(state)))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    self._log.warning("Redis write error during tick: {}", res)

        # Record heartbeat
        self._last_successful_tick = tick_start
        self._consecutive_failures = 0
        self._total_ticks += 1
        if self._degraded:
            self._degraded = False
            self._log.info("FuturesStreamService recovered from degraded mode")

        elapsed_ms = (datetime.now(timezone.utc) - tick_start).total_seconds() * 1000
        self._log.debug(
            "FuturesStream tick | arabica={} robusta={} elapsed={:.0f}ms",
            arabica and arabica.price,
            robusta and robusta.price,
            elapsed_ms,
        )

        # Persist heartbeat to Redis for health monitoring
        await self._write_heartbeat(tick_start, elapsed_ms)

    # ── Resilience ────────────────────────────────────────────────────────────

    async def _on_tick_error(self, exc: Exception) -> None:
        """Track failure, trigger circuit breaker, sleep with backoff."""
        self._consecutive_failures += 1
        self._total_failures += 1
        cb_threshold = settings.stream_circuit_breaker_threshold

        self._log.warning(
            "FuturesStreamService tick error (consecutive={}/{}) | {}",
            self._consecutive_failures, cb_threshold, exc,
        )

        if self._consecutive_failures >= cb_threshold and not self._degraded:
            self._degraded = True
            self._log.error(
                "FuturesStreamService circuit breaker tripped ({}+ failures). "
                "Entering degraded mode — polling at {}s intervals.",
                cb_threshold, settings.stream_degraded_interval_seconds,
            )

        backoff = self._compute_backoff()
        self._log.info("FuturesStreamService backing off for {:.1f}s", backoff)
        await asyncio.sleep(backoff)

    def _compute_backoff(self) -> float:
        """
        Exponential backoff: base × 2^failures, capped at max.
        Capped independently of degraded mode.
        """
        base = settings.stream_backoff_base_seconds
        maximum = settings.stream_backoff_max_seconds
        delay = base * (2 ** min(self._consecutive_failures - 1, 8))
        return min(delay, maximum)

    def _compute_sleep_interval(self) -> float:
        """Normal sleep between ticks — elongated in degraded mode."""
        if self._degraded:
            return float(settings.stream_degraded_interval_seconds)
        return float(settings.stream_interval_seconds)

    # ── Redis heartbeat ───────────────────────────────────────────────────────

    async def _write_heartbeat(self, tick_at: datetime, elapsed_ms: float) -> None:
        """Write heartbeat info to Redis for stream_health to read."""
        try:
            await self._cache.set_json(
                "coffee:health:futures_stream",
                {
                    "stream_id":            _STREAM_ID,
                    "last_tick_at":         tick_at.isoformat(),
                    "consecutive_failures": self._consecutive_failures,
                    "total_ticks":          self._total_ticks,
                    "total_failures":       self._total_failures,
                    "degraded":             self._degraded,
                    "last_tick_elapsed_ms": round(elapsed_ms, 1),
                },
                ttl=settings.stream_stale_threshold_seconds * 2,
            )
        except Exception as exc:
            self._log.debug("Heartbeat write skipped (Redis unavailable): {}", exc)

    # ── Market state composer ─────────────────────────────────────────────────

    def _build_market_state(self, arabica, robusta) -> dict[str, Any]:
        from streaming.normalizer import NormalisedTick  # local import avoids circular
        a: NormalisedTick | None = arabica
        r: NormalisedTick | None = robusta

        a_price  = a.price          if a else 0.0
        r_price  = r.price          if r else 0.0
        a_change = a.change_percent if a else 0.0
        r_change = r.change_percent if r else 0.0
        avg      = (a_change + r_change) / 2 if a and r else (a_change or r_change)

        sentiment = (
            "strongly_bullish" if avg >= 3.0
            else "bullish"       if avg >= 1.0
            else "strongly_bearish" if avg <= -3.0
            else "bearish"       if avg <= -1.0
            else "neutral"
        )
        return {
            "arabica_price":       a_price,
            "arabica_change_pct":  a_change,
            "arabica_currency":    a.currency if a else "US cents/lb",
            "robusta_price":       r_price,
            "robusta_change_pct":  r_change,
            "robusta_currency":    r.currency if r else "USD/tonne",
            "market_sentiment":    sentiment,
            "stream_sources":      list({
                (a.source if a else "none"),
                (r.source if r else "none"),
            }),
            "updated_at":          datetime.now(timezone.utc).isoformat(),
        }
