"""
core/rate_limit.py
==================
Task 3 — Per-endpoint rate limiting via Redis fixed-window counters.

Usage in route files:
    from core.rate_limit import endpoint_rate_limiter
    _limit = endpoint_rate_limiter("chat")       # 20/min
    @router.post("/chat")
    async def chat(..., _rate=Depends(_limit)):
        ...

Limits:
    chat       → settings.rate_limit_chat       (default 20/min)
    market     → settings.rate_limit_market     (default 60/min)
    ingestion  → settings.rate_limit_ingestion  (default  5/min)
    auth       → settings.rate_limit_auth       (default 10/min)
    default    → settings.rate_limit_per_minute (default 100/min)

Fail-open: if Redis is unavailable, requests pass through gracefully.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request, status

from core.config import settings
from core.logger import logger
from core.security import get_api_key

# ── Redis client (lazy singleton) ─────────────────────────────────────────────
_client: aioredis.Redis | None = None


async def _get_redis_client() -> aioredis.Redis | None:
    global _client
    if _client is not None:
        return _client
    try:
        _client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        await _client.ping()
        return _client
    except Exception as exc:
        logger.debug("RateLimiter: Redis unavailable, passthrough mode ({})", exc)
        _client = None
        return None


# ── Per-endpoint limit map ────────────────────────────────────────────────────

_ENDPOINT_LIMITS: dict[str, int] = {
    "chat":      None,   # resolved at runtime from settings
    "market":    None,
    "ingestion": None,
    "auth":      None,
}


def _limit_for(endpoint: str) -> int:
    mapping = {
        "chat":      settings.rate_limit_chat,
        "market":    settings.rate_limit_market,
        "ingestion": settings.rate_limit_ingestion,
        "auth":      settings.rate_limit_auth,
    }
    return mapping.get(endpoint, settings.rate_limit_per_minute)


# ── Core rate-check logic ─────────────────────────────────────────────────────

async def _check(request: Request, api_key: str, endpoint: str, limit: int) -> bool:
    client = await _get_redis_client()
    if client is None:
        return True  # Fail-open

    # Key: API key takes priority; fall back to client IP
    identifier = (
        api_key
        if api_key and api_key not in ("bypass_dev_key", "")
        else getattr(request.client, "host", "127.0.0.1")
    )
    current_minute = int(datetime.now(timezone.utc).timestamp() // 60)
    redis_key = f"coffee:rate_limit:{endpoint}:{identifier}:{current_minute}"

    try:
        pipe = client.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, 60)
        results = await pipe.execute()
        count = results[0]

        if count > limit:
            logger.warning(
                "Rate limit exceeded | endpoint={} identifier={} count={} limit={}",
                endpoint, identifier, count, limit,
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Rate limit exceeded for '{endpoint}': "
                    f"{limit} requests/minute allowed. Retry after 60s."
                ),
                headers={"Retry-After": "60"},
            )
        return True
    except HTTPException:
        raise
    except Exception as exc:
        logger.debug("RateLimiter execution failed: {}", exc)
        return True  # Fail-open on unexpected errors


# ── Public factory ────────────────────────────────────────────────────────────

def endpoint_rate_limiter(endpoint: str) -> Callable:
    """
    Factory that returns a FastAPI Depends-compatible rate-limit checker
    scoped to the given endpoint name.

    Example:
        _limit = endpoint_rate_limiter("chat")

        @router.post("/chat")
        async def chat(..., _rate=Depends(_limit)):
            ...
    """
    limit = _limit_for(endpoint)

    async def _rate_limit_dep(
        request: Request,
        api_key: str = Depends(get_api_key),
    ) -> bool:
        return await _check(request, api_key, endpoint, limit)

    # Give a unique __name__ so FastAPI can distinguish dependencies
    _rate_limit_dep.__name__ = f"rate_limit_{endpoint}"
    return _rate_limit_dep


# ── Legacy compat: single global check_rate_limit (unchanged interface) ───────

async def check_rate_limit(
    request: Request,
    api_key: str = Depends(get_api_key),
) -> bool:
    """Backwards-compatible global rate limiter (uses default per_minute limit)."""
    return await _check(request, api_key, "global", settings.rate_limit_per_minute)
