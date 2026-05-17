"""
core/cache.py
=============
Enterprise Caching Layer.
Provides specialized caches for embeddings, retrieval, weather, and market data.
Uses Redis for shared caching with graceful in-memory fallbacks.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional
import redis.asyncio as aioredis

from core.config import settings
from core.logger import logger

# Default TTLs
TTL_EMBEDDING = 86400 * 7  # 7 days
TTL_WEATHER = 3600         # 1 hour
TTL_MARKET = 300           # 5 minutes


class IntelligenceCache:
    """
    Manager for system-wide caching strategies.
    Specifically optimizes embedding lookups and heavy database queries.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._url = redis_url or settings.redis_url
        self._client: aioredis.Redis | None = None

    async def _get_client(self) -> aioredis.Redis | None:
        if self._client is not None:
            return self._client
        try:
            self._client = aioredis.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            await self._client.ping()
            return self._client
        except Exception as exc:
            logger.debug("IntelligenceCache: Redis unavailable, operating without cache ({})", exc)
            self._client = None
            return None

    def _hash_key(self, prefix: str, text: str) -> str:
        """Generate a compact key using SHA-256 to avoid massive Redis keys."""
        hasher = hashlib.sha256()
        hasher.update(text.encode("utf-8"))
        return f"coffee:cache:{prefix}:{hasher.hexdigest()}"

    # ─── Embedding Cache ──────────────────────────────────────────────────

    async def get_embedding(self, text: str) -> Optional[list[float]]:
        """Retrieve cached embedding vector for a given text."""
        client = await self._get_client()
        if client is None:
            return None

        key = self._hash_key("embed", text)
        try:
            raw = await client.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("Embedding cache hit failed: {}", exc)
        return None

    async def set_embedding(self, text: str, vector: list[float]) -> bool:
        """Cache an embedding vector."""
        client = await self._get_client()
        if client is None:
            return False

        key = self._hash_key("embed", text)
        try:
            await client.setex(key, TTL_EMBEDDING, json.dumps(vector))
            return True
        except Exception as exc:
            logger.debug("Embedding cache store failed: {}", exc)
            return False

    # ─── Generic Data Cache ───────────────────────────────────────────────

    async def get_data(self, prefix: str, key_suffix: str) -> Optional[Any]:
        """Retrieve generic cached data."""
        client = await self._get_client()
        if client is None:
            return None

        key = f"coffee:cache:{prefix}:{key_suffix}"
        try:
            raw = await client.get(key)
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.debug("Data cache read failed for {}: {}", key, exc)
        return None

    async def set_data(self, prefix: str, key_suffix: str, data: Any, ttl: int = 300) -> bool:
        """Cache generic data."""
        client = await self._get_client()
        if client is None:
            return False

        key = f"coffee:cache:{prefix}:{key_suffix}"
        try:
            await client.setex(key, ttl, json.dumps(data, default=str))
            return True
        except Exception as exc:
            logger.debug("Data cache store failed for {}: {}", key, exc)
            return False

def cached(prefix: str, ttl: int = 300):
    """Decorator to cache async function results in Redis."""
    import functools
    from inspect import iscoroutinefunction

    def decorator(func):
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Try to get the cache instance from the first argument (usually self or request)
            # For simplicity, we just instantiate a new one here.
            cache_inst = IntelligenceCache()
            
            # Generate a key based on arguments
            key_parts = [str(a) for a in args[1:]] + [f"{k}={v}" for k, v in kwargs.items()]
            key_suffix = f"{func.__name__}:" + hashlib.md5(str(key_parts).encode()).hexdigest()
            
            cached_val = await cache_inst.get_data(prefix, key_suffix)
            if cached_val is not None:
                return cached_val
            
            result = await func(*args, **kwargs)
            
            # We assume the result is Pydantic model or dict. If Pydantic, convert to dict.
            if hasattr(result, "model_dump"):
                await cache_inst.set_data(prefix, key_suffix, result.model_dump(mode="json"), ttl)
            else:
                await cache_inst.set_data(prefix, key_suffix, result, ttl)
            return result
        return wrapper
    return decorator
