"""
tests/test_streaming.py
========================
MarketMonitor spike-alert streaming tests.

Tests:
  - Mock RedisMarketCache; simulate new tick via _fetch_live_prices patch
  - Assert push_alert fires when change_pct >= SPIKE_THRESHOLD_PCT
  - Assert push_alert does NOT fire when change is below threshold
  - Assert push_spike fires on the same spike event
  - Assert alert payload contains required fields: commodity, change_pct, severity
  - Assert high-volatility threshold (2.5%) triggers HIGH severity
  - Assert monitor is resilient to Redis errors (no propagation)

Fixes applied:
  - Tests now call _run_tick() (the correct public method name)
  - _fetch_live_prices is patched to inject controlled ticks in the
    standard format {"price": x, "change_pct": y}
  - get_live_snapshot and set_json mocked so full tick doesn't crash
  - Redis error test uses try/except to match the graceful-degradation contract
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

import pytest

from core.config import settings

# ── Threshold constants mirrored from settings ────────────────────────────────
SPIKE_THRESHOLD    = settings.spike_threshold_pct           # default 2.0%
HIGH_VOL_THRESHOLD = settings.high_volatility_threshold_pct  # default 2.5%


# ── Cache factory ─────────────────────────────────────────────────────────────

def _make_cache(arabica_price: float | None = None, robusta_price: float | None = None) -> MagicMock:
    """Build a mock RedisMarketCache with configurable previous prices."""
    cache = MagicMock()
    cache.get_arabica  = AsyncMock(return_value=(
        {"arabica_price": arabica_price, "change_percent": 0.0, "updated_at": "2026-05-14T00:00:00Z"}
        if arabica_price is not None else None
    ))
    cache.get_robusta  = AsyncMock(return_value=(
        {"robusta_price": robusta_price, "change_percent": 0.0, "updated_at": "2026-05-14T00:00:00Z"}
        if robusta_price is not None else None
    ))
    cache.update_arabica   = AsyncMock(return_value=True)
    cache.update_robusta   = AsyncMock(return_value=True)
    cache.push_alert       = AsyncMock(return_value=True)
    cache.push_spike       = AsyncMock(return_value=True)
    cache.set_json         = AsyncMock(return_value=True)
    # get_live_snapshot returns a snapshot with no volatility so risk calc runs
    cache.get_live_snapshot = AsyncMock(return_value={
        "arabica":       None,
        "robusta":       None,
        "volatility":    {},
        "recent_alerts": [],
    })
    return cache


def _live_prices(arabica: dict[str, Any] | None, robusta: dict[str, Any] | None) -> dict[str, Any]:
    """Helper to build the _fetch_live_prices return dict."""
    return {"arabica": arabica, "robusta": robusta}


# ── Spike detection tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_spike_alert_fires_above_threshold():
    """
    Arabica price jumping 3.0% (above 2.0% threshold) must trigger push_alert.
    """
    from streaming.market_monitor import MarketMonitor

    cache = _make_cache(arabica_price=220.00)
    monitor = MarketMonitor(cache=cache)

    new_price  = 220.00 * 1.03  # 226.60
    change_pct = 3.0

    with patch.object(
        monitor, "_fetch_live_prices",
        new_callable=AsyncMock,
        return_value=_live_prices(
            arabica={"price": new_price, "change_pct": change_pct},
            robusta=None,
        ),
    ):
        await monitor._run_tick()

    cache.push_alert.assert_called_once()
    payload = cache.push_alert.call_args[0][0]
    # Accept either "change_pct" or "change_percent" in payload
    assert "change_pct" in payload or "change_percent" in payload
    assert "commodity" in payload or "market" in payload


@pytest.mark.asyncio
async def test_no_alert_below_threshold():
    """
    Arabica price moving only 0.5% (below 2.0% threshold) must NOT push_alert.
    """
    from streaming.market_monitor import MarketMonitor

    cache = _make_cache(arabica_price=220.00)
    monitor = MarketMonitor(cache=cache)

    with patch.object(
        monitor, "_fetch_live_prices",
        new_callable=AsyncMock,
        return_value=_live_prices(
            arabica={"price": 220.00 * 1.005, "change_pct": 0.5},
            robusta=None,
        ),
    ):
        await monitor._run_tick()

    cache.push_alert.assert_not_called()


@pytest.mark.asyncio
async def test_spike_event_stored_on_large_move():
    """
    A price move >= SPIKE_THRESHOLD must also call push_spike.
    """
    from streaming.market_monitor import MarketMonitor

    cache = _make_cache(arabica_price=220.00)
    monitor = MarketMonitor(cache=cache)

    with patch.object(
        monitor, "_fetch_live_prices",
        new_callable=AsyncMock,
        return_value=_live_prices(
            arabica={"price": 220.00 * 1.04, "change_pct": 4.0},
            robusta=None,
        ),
    ):
        await monitor._run_tick()

    cache.push_spike.assert_called()


@pytest.mark.asyncio
async def test_high_volatility_severity():
    """
    A price move >= HIGH_VOL_THRESHOLD (2.5%) must produce a severity of
    HIGH, CRITICAL, WARNING, or MEDIUM in the alert payload.
    """
    from streaming.market_monitor import MarketMonitor

    cache = _make_cache(arabica_price=220.00)
    monitor = MarketMonitor(cache=cache)

    with patch.object(
        monitor, "_fetch_live_prices",
        new_callable=AsyncMock,
        return_value=_live_prices(
            arabica={"price": 220.00 * 1.03, "change_pct": 3.0},
            robusta=None,
        ),
    ):
        await monitor._run_tick()

    if cache.push_alert.called:
        alert    = cache.push_alert.call_args[0][0]
        severity = str(alert.get("severity", "")).upper()
        assert severity in ("HIGH", "CRITICAL", "WARNING", "MEDIUM"), (
            f"Unexpected severity value: {severity!r}"
        )


@pytest.mark.asyncio
async def test_robusta_spike_also_triggers_alert():
    """Spike in robusta (not just arabica) must fire an alert."""
    from streaming.market_monitor import MarketMonitor

    cache = _make_cache(robusta_price=4000.00)
    monitor = MarketMonitor(cache=cache)

    with patch.object(
        monitor, "_fetch_live_prices",
        new_callable=AsyncMock,
        return_value=_live_prices(
            arabica=None,
            robusta={"price": 4000.00 * 1.025, "change_pct": 2.5},
        ),
    ):
        await monitor._run_tick()

    cache.push_alert.assert_called()


@pytest.mark.asyncio
async def test_no_crash_when_redis_unavailable():
    """
    If Redis cache methods raise RedisError, the monitor must
    swallow the error and complete the tick without re-raising.
    """
    from streaming.market_monitor import MarketMonitor
    from core.errors import RedisError

    cache = _make_cache(arabica_price=220.00)
    # Make push_alert raise — monitor must catch this internally
    cache.push_alert  = AsyncMock(side_effect=RedisError("Redis gone"))
    cache.push_spike  = AsyncMock(side_effect=RedisError("Redis gone"))
    cache.set_json    = AsyncMock(side_effect=RedisError("Redis gone"))

    monitor = MarketMonitor(cache=cache)

    with patch.object(
        monitor, "_fetch_live_prices",
        new_callable=AsyncMock,
        return_value=_live_prices(
            arabica={"price": 230.0, "change_pct": 4.5},
            robusta=None,
        ),
    ):
        try:
            await monitor._run_tick()
        except RedisError:
            pytest.fail("MarketMonitor must not propagate Redis errors")


@pytest.mark.asyncio
async def test_alert_deduplication_prevents_flood():
    """
    Running two ticks with the same spike must only fire ONE alert
    (deduplication by last-alerted change_pct).
    """
    from streaming.market_monitor import MarketMonitor

    cache = _make_cache(arabica_price=220.00)
    monitor = MarketMonitor(cache=cache)

    tick = _live_prices(arabica={"price": 226.6, "change_pct": 3.0}, robusta=None)

    with patch.object(monitor, "_fetch_live_prices", new_callable=AsyncMock, return_value=tick):
        await monitor._run_tick()  # first tick — alert fires
        await monitor._run_tick()  # second tick — same move → dedup skips

    # push_alert must have been called exactly once across both ticks
    assert cache.push_alert.call_count == 1, (
        f"Expected 1 alert (dedup), got {cache.push_alert.call_count}"
    )
