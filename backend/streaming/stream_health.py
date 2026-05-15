"""
streaming/stream_health.py
===========================
Stream Health Tracker — real-time observability for all live data feeds.

Tracks per-stream:
  ✅ last_tick_at          — when was data last successfully received?
  ✅ is_stale              — has the feed gone silent beyond threshold?
  ✅ consecutive_failures  — how many ticks in a row have failed?
  ✅ reconnect_count        — how many times has the service auto-reconnected?
  ✅ latency_ms_avg        — rolling average API latency
  ✅ total_ticks           — total successful ticks ever
  ✅ degraded              — is the service in circuit-breaker degraded mode?

Architecture:
  - Each streaming service (FuturesStreamService, MarketMonitor) calls
    health_tracker.record_success(stream_id, latency_ms) / record_failure(stream_id)
    after every tick.
  - StreamHealthTracker.get_report() returns a full health snapshot usable
    by the /health/streams API endpoint and the IntelligenceLoop.
  - The tracker writes a health snapshot to Redis key coffee:health:streams
    every stream_health_report_interval_seconds seconds for external monitoring.

Usage:
    tracker = StreamHealthTracker(cache=redis_cache)
    await tracker.start()   # runs as asyncio.Task

    # In FuturesStreamService._tick():
    await tracker.record_success("futures_stream", latency_ms=142.3)

    # In FuturesStreamService._on_tick_error():
    await tracker.record_failure("futures_stream")

    # In /api/v1/health/streams:
    report = tracker.get_report()
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from core.config import settings
from core.logger import logger, bind_context

# All known stream IDs the tracker manages by default
_KNOWN_STREAMS = ("futures_stream", "market_monitor", "intelligence_loop")

# Staleness: if no successful tick for this many seconds, mark as stale
_STALE_THRESHOLD_S = settings.stream_stale_threshold_seconds

# Rolling latency window size
_LATENCY_WINDOW = 20


@dataclass
class StreamState:
    """Mutable health state for a single streaming feed."""
    stream_id:            str
    last_tick_at:         datetime | None = None
    consecutive_failures: int             = 0
    total_failures:       int             = 0
    total_ticks:          int             = 0
    reconnect_count:      int             = 0
    degraded:             bool            = False
    _latency_window:      deque           = field(default_factory=lambda: deque(maxlen=_LATENCY_WINDOW))

    @property
    def is_stale(self) -> bool:
        if self.last_tick_at is None:
            return True
        age_s = (datetime.now(timezone.utc) - self.last_tick_at).total_seconds()
        return age_s > _STALE_THRESHOLD_S

    @property
    def latency_ms_avg(self) -> float | None:
        if not self._latency_window:
            return None
        return round(sum(self._latency_window) / len(self._latency_window), 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stream_id":            self.stream_id,
            "status":               "degraded" if self.degraded else ("stale" if self.is_stale else "healthy"),
            "is_stale":             self.is_stale,
            "degraded":             self.degraded,
            "last_tick_at":         self.last_tick_at.isoformat() if self.last_tick_at else None,
            "consecutive_failures": self.consecutive_failures,
            "total_failures":       self.total_failures,
            "total_ticks":          self.total_ticks,
            "reconnect_count":      self.reconnect_count,
            "latency_ms_avg":       self.latency_ms_avg,
        }


class StreamHealthTracker:
    """
    Central health tracker for all streaming feeds.

    Thread-safe for asyncio (single-threaded event loop).
    Writes aggregate health report to Redis periodically.
    """

    def __init__(self, cache=None) -> None:
        self._cache = cache        # RedisMarketCache | None
        self._streams: dict[str, StreamState] = {
            sid: StreamState(stream_id=sid)
            for sid in _KNOWN_STREAMS
        }
        self._running = False
        self._log     = bind_context(stream_id="health_tracker")

    # ── Recording API ─────────────────────────────────────────────────────────

    def record_success(self, stream_id: str, latency_ms: float | None = None) -> None:
        """
        Call after every successful tick.

        Args:
            stream_id:  Which feed ("futures_stream", "market_monitor", etc.)
            latency_ms: API round-trip latency in milliseconds (optional).
        """
        state = self._get_or_create(stream_id)
        state.last_tick_at         = datetime.now(timezone.utc)
        state.consecutive_failures = 0
        state.total_ticks         += 1
        if latency_ms is not None:
            state._latency_window.append(latency_ms)

    def record_failure(self, stream_id: str) -> None:
        """
        Call after every failed tick.

        Args:
            stream_id: Which feed failed.
        """
        state = self._get_or_create(stream_id)
        state.consecutive_failures += 1
        state.total_failures       += 1

    def record_reconnect(self, stream_id: str) -> None:
        """Increment the reconnect counter for a given stream."""
        self._get_or_create(stream_id).reconnect_count += 1

    def set_degraded(self, stream_id: str, degraded: bool) -> None:
        """Synchronise circuit-breaker state into health tracker."""
        self._get_or_create(stream_id).degraded = degraded

    # ── Report API ────────────────────────────────────────────────────────────

    def get_report(self) -> dict[str, Any]:
        """
        Return a full health report for all tracked streams.

        Example output:
            {
              "overall_status": "healthy",
              "streams": {
                "futures_stream": {"status": "healthy", "latency_ms_avg": 142.1, ...},
                "market_monitor": {"status": "stale", ...},
              },
              "generated_at": "2026-05-15T08:00:00Z"
            }
        """
        stream_reports = {
            sid: state.to_dict()
            for sid, state in self._streams.items()
        }

        # Overall status: worst case across all streams
        statuses = [s["status"] for s in stream_reports.values()]
        if "degraded" in statuses:
            overall = "degraded"
        elif "stale" in statuses:
            overall = "stale"
        else:
            overall = "healthy"

        return {
            "overall_status": overall,
            "streams":        stream_reports,
            "stale_threshold_seconds": _STALE_THRESHOLD_S,
            "generated_at":   datetime.now(timezone.utc).isoformat(),
        }

    def get_stream(self, stream_id: str) -> dict[str, Any] | None:
        """Return health state for a single stream, or None if unknown."""
        state = self._streams.get(stream_id)
        return state.to_dict() if state else None

    # ── Background reporter ───────────────────────────────────────────────────

    async def start(self) -> None:
        """Run forever — periodically writes health report to Redis."""
        self._running = True
        interval = settings.stream_health_report_interval_seconds
        self._log.info("StreamHealthTracker started | report_interval={}s", interval)
        while self._running:
            await asyncio.sleep(interval)
            try:
                await self._write_health_to_redis()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self._log.debug("StreamHealthTracker report write failed: {}", exc)

    async def stop(self) -> None:
        self._running = False

    # ── Internals ─────────────────────────────────────────────────────────────

    def _get_or_create(self, stream_id: str) -> StreamState:
        if stream_id not in self._streams:
            self._streams[stream_id] = StreamState(stream_id=stream_id)
        return self._streams[stream_id]

    async def _write_health_to_redis(self) -> None:
        if self._cache is None:
            return
        report = self.get_report()
        try:
            await self._cache.set_json(
                "coffee:health:streams",
                report,
                ttl=settings.stream_health_report_interval_seconds * 3,
            )
            self._log.debug(
                "StreamHealth report written | overall={}",
                report["overall_status"],
            )
        except Exception as exc:
            self._log.debug("StreamHealth Redis write skipped: {}", exc)
