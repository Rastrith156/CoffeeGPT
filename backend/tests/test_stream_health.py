"""
tests/test_stream_health.py
============================
StreamHealthTracker unit tests.

Tests (all offline — no Redis, no network):
  - record_success marks stream as healthy, non-stale
  - record_failure increments consecutive_failures
  - is_stale returns True when last_tick_at is None or old
  - is_stale returns False after a fresh success
  - get_report overall_status reflects worst-case stream
  - latency_ms_avg computes rolling average correctly
  - reconnect_count increments via record_reconnect
  - set_degraded propagates into stream state and get_report
  - get_stream returns None for unknown stream_id
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta

import pytest

from streaming.stream_health import StreamHealthTracker, StreamState, _STALE_THRESHOLD_S


@pytest.fixture
def tracker() -> StreamHealthTracker:
    return StreamHealthTracker(cache=None)


# ── Freshness / staleness ─────────────────────────────────────────────────────

def test_stream_is_stale_when_no_tick(tracker: StreamHealthTracker):
    """An unknown/uninitialised stream must be considered stale."""
    state = StreamState(stream_id="test")
    assert state.is_stale is True


def test_stream_is_not_stale_after_fresh_success(tracker: StreamHealthTracker):
    tracker.record_success("futures_stream", latency_ms=50.0)
    state = tracker._streams["futures_stream"]
    assert state.is_stale is False


def test_stream_is_stale_after_threshold(tracker: StreamHealthTracker):
    """Manually set last_tick_at to far past → should be stale."""
    tracker.record_success("futures_stream")
    state = tracker._streams["futures_stream"]
    # Backdate the last tick beyond the stale threshold
    state.last_tick_at = datetime.now(timezone.utc) - timedelta(seconds=_STALE_THRESHOLD_S + 10)
    assert state.is_stale is True


# ── Failure tracking ──────────────────────────────────────────────────────────

def test_failure_increments_counters(tracker: StreamHealthTracker):
    tracker.record_failure("futures_stream")
    tracker.record_failure("futures_stream")
    state = tracker._streams["futures_stream"]
    assert state.consecutive_failures == 2
    assert state.total_failures       == 2


def test_success_resets_consecutive_failures(tracker: StreamHealthTracker):
    tracker.record_failure("futures_stream")
    tracker.record_failure("futures_stream")
    tracker.record_success("futures_stream")
    assert tracker._streams["futures_stream"].consecutive_failures == 0


def test_success_increments_total_ticks(tracker: StreamHealthTracker):
    tracker.record_success("market_monitor")
    tracker.record_success("market_monitor")
    assert tracker._streams["market_monitor"].total_ticks == 2


# ── Latency ───────────────────────────────────────────────────────────────────

def test_latency_avg_computed_correctly(tracker: StreamHealthTracker):
    for ms in (100.0, 200.0, 150.0):
        tracker.record_success("futures_stream", latency_ms=ms)
    avg = tracker._streams["futures_stream"].latency_ms_avg
    assert avg == pytest.approx(150.0)


def test_latency_none_when_no_data(tracker: StreamHealthTracker):
    assert tracker._streams["futures_stream"].latency_ms_avg is None


# ── Reconnect count ───────────────────────────────────────────────────────────

def test_reconnect_count_increments(tracker: StreamHealthTracker):
    tracker.record_reconnect("futures_stream")
    tracker.record_reconnect("futures_stream")
    assert tracker._streams["futures_stream"].reconnect_count == 2


# ── Degraded mode ─────────────────────────────────────────────────────────────

def test_set_degraded_updates_state(tracker: StreamHealthTracker):
    tracker.set_degraded("futures_stream", degraded=True)
    assert tracker._streams["futures_stream"].degraded is True
    tracker.set_degraded("futures_stream", degraded=False)
    assert tracker._streams["futures_stream"].degraded is False


def test_degraded_stream_reported_in_overall_status(tracker: StreamHealthTracker):
    # Make one stream look fresh/healthy first
    tracker.record_success("futures_stream")
    # Then mark it degraded
    tracker.set_degraded("futures_stream", degraded=True)
    report = tracker.get_report()
    assert report["overall_status"] == "degraded"


# ── get_report ────────────────────────────────────────────────────────────────

def test_healthy_report_when_all_streams_ok(tracker: StreamHealthTracker):
    tracker.record_success("futures_stream")
    tracker.record_success("market_monitor")
    tracker.record_success("intelligence_loop")
    report = tracker.get_report()
    assert report["overall_status"] == "healthy"
    assert "futures_stream"    in report["streams"]
    assert "market_monitor"    in report["streams"]
    assert "intelligence_loop" in report["streams"]


def test_stale_status_when_no_ticks_ever():
    """Fresh tracker with no ticks must report stale."""
    tracker = StreamHealthTracker(cache=None)
    report = tracker.get_report()
    # All pre-registered streams have last_tick_at=None → stale
    assert report["overall_status"] in ("stale", "degraded")


def test_get_stream_returns_none_for_unknown():
    tracker = StreamHealthTracker(cache=None)
    assert tracker.get_stream("nonexistent_stream") is None


def test_get_stream_returns_dict_for_known(tracker: StreamHealthTracker):
    tracker.record_success("futures_stream", latency_ms=80.0)
    info = tracker.get_stream("futures_stream")
    assert info is not None
    assert "status" in info
    assert "latency_ms_avg" in info
    assert info["latency_ms_avg"] == pytest.approx(80.0)


# ── Auto-register unknown stream_id ──────────────────────────────────────────

def test_unknown_stream_auto_registered(tracker: StreamHealthTracker):
    """record_success with an unknown stream_id should auto-register it."""
    tracker.record_success("my_new_stream", latency_ms=30.0)
    assert "my_new_stream" in tracker._streams
    assert tracker._streams["my_new_stream"].total_ticks == 1
