"""
core/rate_limit.py
==================
Enterprise Rate Limiter protecting APIs and WebSockets from spam
and exhaustion attacks using Redis Fixed-Window/Token-Bucket counters.
"""
from __future__ import annotations

from datetime import datetime, timezone

import redis.asyncio as aioredis
from fastapi import Depends, HTTPException, Request

from core.config import settings
from core.logger import logger
from core.security import get_api_key

# Global async Redis client instance initialized lazily for rate limiting
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
        logger.debug("RateLimiter: Redis unavailable, operating in passthrough mode ({})", exc)
        _client = None
        return None


async def check_rate_limit(
    request: Request,
    api_key: str = Depends(get_api_key),
) -> bool:
    """
    FastAPI dependency enforcing strict requests-per-minute thresholds per API Key
    or client IP. Operates in fail-open passthrough mode if Redis is offline.
    """
    client = await _get_redis_client()
    if client is None:
        # Graceful degradation circuit breaker: do not crash API if cache goes down
        return True

    # Identify caller by verified API Key or source IP address
    identifier = api_key if api_key and api_key != "bypass_dev_key" else getattr(request.client, "host", "127.0.0.1")
    current_minute = int(datetime.now(timezone.utc).timestamp() // 60)
    limit_key = f"coffee:rate_limit:{identifier}:{current_minute}"

    try:
        pipe = client.pipeline()
        pipe.incr(limit_key)
        pipe.expire(limit_key, 60)
        results = await pipe.execute()
        current_count = results[0]

        if current_count > settings.rate_limit_per_minute:
            logger.warning("Rate limit exceeded for caller identifier: {}", identifier)
            raise HTTPException(
                status_code=429,
                detail=f"Too Many Requests. Rate limit of {settings.rate_limit_per_minute} req/min exceeded.",
            )
        return True
    except HTTPException:
        raise
    except Exception as exc:
        logger.debug("RateLimiter Redis execution failed: {}", exc)
        return True
