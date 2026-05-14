"""
api/live.py
===========
Live Market API — exposes Redis hot-cache data via REST endpoints.

Endpoints:
  GET /live/snapshot       — full live market snapshot
  GET /live/arabica        — arabica price
  GET /live/robusta        — robusta price
  GET /live/alerts         — recent alerts
  GET /live/risk           — current risk score
  GET /live/insights       — latest intelligence insights
  GET /live/health         — streaming layer health
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from core.dependencies import get_redis_cache

router = APIRouter(prefix="/live", tags=["live_market"])


def _cache_required(cache=Depends(get_redis_cache)):
    if cache is None:
        raise HTTPException(
            status_code=503,
            detail="Live streaming layer is not available. Redis may be offline.",
        )
    return cache


@router.get("/snapshot", summary="Full live market snapshot from Redis")
async def live_snapshot(cache=Depends(_cache_required)):
    """Returns the combined live market state from the Redis hot cache."""
    data = await cache.get_live_snapshot()
    return {
        "status": "ok",
        "data": data,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/arabica", summary="Live Arabica futures price")
async def live_arabica(cache=Depends(_cache_required)):
    data = await cache.get_arabica()
    if not data:
        raise HTTPException(status_code=404, detail="Arabica live data not yet available.")
    return {"status": "ok", "data": data}


@router.get("/robusta", summary="Live Robusta futures price")
async def live_robusta(cache=Depends(_cache_required)):
    data = await cache.get_robusta()
    if not data:
        raise HTTPException(status_code=404, detail="Robusta live data not yet available.")
    return {"status": "ok", "data": data}


@router.get("/alerts", summary="Recent market alerts")
async def live_alerts(count: int = 10, cache=Depends(_cache_required)):
    """Returns the most recent market alerts (spikes, volatility, risk)."""
    count = min(max(count, 1), 50)
    alerts = await cache.get_alerts(count)
    return {
        "status": "ok",
        "count": len(alerts),
        "alerts": alerts,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/risk", summary="Current market risk score")
async def live_risk(cache=Depends(_cache_required)):
    """Returns the live risk score and recommendation from the market monitor."""
    risk = await cache.get_json("coffee:live:risk")
    if not risk:
        return {
            "status": "pending",
            "message": "Risk score not yet computed. Market monitor starting up.",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        }
    return {"status": "ok", "data": risk}


@router.get("/insights", summary="Latest autonomous intelligence insights")
async def live_insights(count: int = 5, cache=Depends(_cache_required)):
    """Returns AI-generated market insights from the intelligence loop."""
    count = min(max(count, 1), 20)
    insights = await cache.get_list_json("coffee:live:intelligence_insights", count)
    return {
        "status": "ok",
        "count": len(insights),
        "insights": insights,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/health", summary="Streaming layer health check")
async def live_health(cache=Depends(get_redis_cache)):
    """Check whether the Redis streaming layer is reachable."""
    if cache is None:
        return {
            "status": "unavailable",
            "redis": False,
            "message": "Streaming layer not configured.",
        }
    healthy = await cache.is_healthy()
    return {
        "status": "ok" if healthy else "degraded",
        "redis": healthy,
        "message": "Redis hot cache is online." if healthy else "Redis is unreachable.",
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
