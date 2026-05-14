"""
core/health.py
==============
Task 5 — Deep health check with per-service latency.

Pings: Qdrant, Redis, PostgreSQL, LMStudio (each independently).
Returns structured JSON:
  {
    "status": "healthy" | "degraded" | "unhealthy",
    "services": [
      { "name": "redis",    "status": "ok",   "latency_ms": 1.2 },
      { "name": "qdrant",   "status": "ok",   "latency_ms": 4.5 },
      { "name": "postgres", "status": "error","latency_ms": 0.0, "detail": "..." },
      { "name": "lmstudio", "status": "ok",   "latency_ms": 38.0 }
    ],
    "checked_at": "2026-05-14T12:00:00Z"
  }

Wired to GET /api/v1/health (replaces existing stub).
Returns HTTP 503 if any critical service is unhealthy.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx
import redis.asyncio as aioredis
import sqlalchemy

from core.config import settings
from core.logger import logger


class ServiceStatus:
    OK    = "ok"
    ERROR = "error"
    WARN  = "warn"


async def _check_redis() -> dict[str, Any]:
    """Ping Redis and measure round-trip latency."""
    t0 = time.perf_counter()
    try:
        client = aioredis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await client.ping()
        await client.aclose()
        return {
            "name": "redis",
            "status": ServiceStatus.OK,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        }
    except Exception as exc:
        return {
            "name": "redis",
            "status": ServiceStatus.ERROR,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": str(exc)[:120],
        }


async def _check_qdrant() -> dict[str, Any]:
    """HTTP GET to Qdrant /healthz."""
    t0 = time.perf_counter()
    url = f"http://{settings.qdrant_host}:{settings.qdrant_port}/healthz"
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(url)
            ok = resp.status_code == 200
            return {
                "name": "qdrant",
                "status": ServiceStatus.OK if ok else ServiceStatus.WARN,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                "http_status": resp.status_code,
            }
    except Exception as exc:
        return {
            "name": "qdrant",
            "status": ServiceStatus.ERROR,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": str(exc)[:120],
        }


async def _check_postgres() -> dict[str, Any]:
    """SELECT 1 against PostgreSQL (sync engine in thread to keep async clean)."""
    import asyncio

    t0 = time.perf_counter()

    def _sync_ping():
        try:
            engine = sqlalchemy.create_engine(
                settings.database_url,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 3},
            )
            with engine.connect() as conn:
                conn.execute(sqlalchemy.text("SELECT 1"))
            engine.dispose()
            return None
        except Exception as exc:
            return str(exc)[:120]

    error = await asyncio.to_thread(_sync_ping)
    return {
        "name": "postgres",
        "status": ServiceStatus.OK if error is None else ServiceStatus.ERROR,
        "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
        **({"detail": error} if error else {}),
    }


async def _check_lmstudio() -> dict[str, Any]:
    """GET /v1/models from LMStudio (or any OpenAI-compat local server)."""
    t0 = time.perf_counter()
    url = f"{settings.lmstudio_base_url.rstrip('/')}/v1/models"
    headers = {}
    if settings.lmstudio_api_token:
        headers["Authorization"] = f"Bearer {settings.lmstudio_api_token}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url, headers=headers)
            ok = resp.status_code == 200
            return {
                "name": "lmstudio",
                "status": ServiceStatus.OK if ok else ServiceStatus.WARN,
                "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
                "http_status": resp.status_code,
            }
    except Exception as exc:
        return {
            "name": "lmstudio",
            "status": ServiceStatus.WARN,   # LMStudio may be intentionally offline
            "latency_ms": round((time.perf_counter() - t0) * 1000, 2),
            "detail": str(exc)[:120],
        }


async def deep_health_check() -> dict[str, Any]:
    """
    Run all service health checks in parallel and aggregate results.
    Returns the full structured health report.
    """
    import asyncio

    results = await asyncio.gather(
        _check_redis(),
        _check_qdrant(),
        _check_postgres(),
        _check_lmstudio(),
        return_exceptions=True,
    )

    services: list[dict] = []
    for r in results:
        if isinstance(r, Exception):
            services.append({"name": "unknown", "status": ServiceStatus.ERROR, "detail": str(r)})
        else:
            services.append(r)

    # Determine overall status
    statuses = {s["status"] for s in services}
    if ServiceStatus.ERROR in statuses:
        overall = "degraded"
    else:
        overall = "healthy"

    # If BOTH Redis and Postgres are down → truly unhealthy
    critical_errors = [s for s in services if s["status"] == ServiceStatus.ERROR and s["name"] in ("redis", "postgres")]
    if len(critical_errors) >= 2:
        overall = "unhealthy"

    report = {
        "status": overall,
        "services": services,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "version": settings.app_version,
        "environment": settings.environment,
    }

    logger.debug("Deep health check: status={} services={}", overall, {s["name"]: s["status"] for s in services})
    return report
