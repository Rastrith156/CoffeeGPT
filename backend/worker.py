"""
worker.py
=========
Production-Grade Background Worker Process.

Adopts WorkerSupervisor for full lifecycle management:
  ✅ Task registration with automatic restart on failure
  ✅ Exponential backoff between restarts
  ✅ Circuit breaker after consecutive failures
  ✅ Graceful shutdown on SIGINT / SIGTERM
  ✅ Health reporting via supervisor.get_health_report()
  ✅ Per-service stream health tracking (StreamHealthTracker)

Registered services:
  futures_stream       — live arabica/robusta price polling
  market_monitor       — spike/volatility/risk detection loop
  state_snapshotter    — Redis → Postgres periodic persistence
  stream_health        — health report writer (Redis key)
  retention_sweep      — data retention cleanup (daily)
"""
from __future__ import annotations

import asyncio
import sys

from core.logger import logger, setup_logger
from core.worker_supervisor import WorkerSupervisor
from core.errors import InitializationError


# ── Service factories (imported lazily to allow clean error logging) ───────────

def _build_futures_stream():
    """Factory for FuturesStreamService — returns the .start() coroutine factory."""
    from streaming.futures_stream import FuturesStreamService
    from streaming.redis_cache import RedisMarketCache
    from streaming.stream_health import StreamHealthTracker

    cache = RedisMarketCache()
    tracker = StreamHealthTracker(cache=cache)

    # Attach health tracker to the stream service
    svc = FuturesStreamService(cache=cache, health_tracker=tracker)
    return svc.start


def _build_market_monitor():
    """Factory for MarketMonitor."""
    from streaming.market_monitor import MarketMonitor
    from streaming.redis_cache import RedisMarketCache
    from streaming.stream_health import StreamHealthTracker

    cache = RedisMarketCache()
    tracker = StreamHealthTracker(cache=cache)
    monitor = MarketMonitor(cache=cache, health_tracker=tracker)
    return monitor.start


def _build_state_snapshotter():
    """Factory for StateSnapshotter."""
    from streaming.state_snapshotter import StateSnapshotter
    from streaming.redis_cache import RedisMarketCache

    try:
        from core.database import get_session_factory
        db_factory = get_session_factory()
    except Exception:
        db_factory = None

    cache = RedisMarketCache()
    snapshotter = StateSnapshotter(cache=cache, db_factory=db_factory)
    return snapshotter.start


def _build_stream_health_reporter():
    """Factory for StreamHealthTracker background writer."""
    from streaming.stream_health import StreamHealthTracker
    from streaming.redis_cache import RedisMarketCache

    cache = RedisMarketCache()
    tracker = StreamHealthTracker(cache=cache)
    return tracker.start


async def _retention_loop() -> None:
    """Daily retention sweep loop."""
    from services.retention_service import RetentionService

    svc = RetentionService()
    while True:
        try:
            await svc.run_retention_sweep()
            logger.info("Retention sweep completed successfully")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Retention sweep failed (will retry in 24 h): {}", exc)
        await asyncio.sleep(86_400)  # 24 hours


# ── Main entrypoint ───────────────────────────────────────────────────────────

async def main() -> None:
    setup_logger()
    logger.info("CoffeeGPT Background Worker starting...")

    supervisor = WorkerSupervisor(
        restart_backoff_base=2.0,
        restart_backoff_max=120.0,
        circuit_breaker_threshold=5,
    )

    # ── Register all supervised tasks ─────────────────────────────────────────
    registration_errors: list[str] = []

    services = [
        ("futures_stream",    _build_futures_stream,           True,  10),
        ("market_monitor",    _build_market_monitor,           True,  10),
        ("state_snapshotter", _build_state_snapshotter,        True,  5),
        ("stream_health",     _build_stream_health_reporter,   True,  5),
        ("retention_sweep",   lambda: _retention_loop,         True,  3),
    ]

    for name, factory_fn, restart, max_attempts in services:
        try:
            coro_factory = factory_fn()
            supervisor.register_task(
                name=name,
                coro_factory=coro_factory,
                restart_on_failure=restart,
                max_restart_attempts=max_attempts,
            )
            logger.info("Registered worker task: {}", name)
        except InitializationError as exc:
            logger.warning("Task '{}' already registered ({})", name, exc)
        except Exception as exc:
            registration_errors.append(f"{name}: {exc}")
            logger.error("Failed to register task '{}': {}", name, exc)

    if registration_errors:
        logger.warning(
            "{} task(s) failed to register: {}",
            len(registration_errors),
            ", ".join(registration_errors),
        )

    if not supervisor._tasks:
        logger.critical("No tasks registered — worker cannot start.")
        sys.exit(1)

    logger.info(
        "WorkerSupervisor starting with {} registered tasks",
        len(supervisor._tasks),
    )

    try:
        await supervisor.start()
    except Exception as exc:
        logger.critical("WorkerSupervisor crashed: {}", exc)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
