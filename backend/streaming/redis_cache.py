"""
streaming/redis_cache.py
========================
HOT LAYER — Real-time Redis cache for live market state.

Stores and retrieves:
  - Latest futures prices (arabica / robusta)
  - Volatility signals
  - Market alerts
  - Spike events

Redis keys follow the prefix  coffee:live:<key>
TTL defaults: prices = 60 s, alerts = 300 s, meta = 120 s
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from core.config import settings
from core.logger import logger

# ─── TTL constants ─────────────────────────────────────────────────────────
TTL_PRICE = 60        # seconds — live price entry
TTL_ALERT = 300       # seconds — generated alert
TTL_META  = 120       # seconds — misc metadata

# ─── Key templates ─────────────────────────────────────────────────────────
KEY_ARABICA        = "coffee:live:arabica"
KEY_ROBUSTA        = "coffee:live:robusta"
KEY_VOLATILITY     = "coffee:live:volatility"
KEY_MARKET_STATE   = "coffee:live:market_state"
KEY_ALERTS         = "coffee:live:alerts"          # Redis list
KEY_SPIKE_EVENT    = "coffee:live:spike_latest"


class RedisMarketCache:
    """
    Async Redis wrapper for the live market hot-cache layer.
    All methods fail gracefully when Redis is unavailable.

    Reconnect behaviour: if _client is None (first call or after a previous
    failure), a new connection is attempted on every call to _get_client().
    This means the cache transparently recovers when Redis comes back online
    without requiring a server restart.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._url = redis_url or settings.redis_url
        self._client: aioredis.Redis | None = None

    async def _get_client(self) -> aioredis.Redis | None:
        # Fast path: existing healthy client
        if self._client is not None:
            try:
                await self._client.ping()
                return self._client
            except Exception:
                # Connection dropped — reset and fall through to reconnect
                logger.warning("RedisMarketCache: connection lost, attempting reconnect to {}", self._url)
                try:
                    await self._client.aclose()
                except Exception:
                    pass
                self._client = None

        # Reconnect attempt
        try:
            self._client = aioredis.from_url(
                self._url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            await self._client.ping()
            logger.info("RedisMarketCache connected to {}", self._url)
            return self._client
        except Exception as exc:
            logger.warning("RedisMarketCache: Redis unavailable ({})", exc)
            # Always reset to None so the next call retries
            self._client = None
            return None

    # ─── Generic helpers ──────────────────────────────────────────────────

    async def set_json(self, key: str, data: dict[str, Any], ttl: int = TTL_META) -> bool:
        client = await self._get_client()
        if client is None:
            return False
        try:
            await client.setex(key, ttl, json.dumps(data, default=str))
            return True
        except Exception as exc:
            logger.warning("RedisMarketCache.set_json error: {}", exc)
            return False

    async def get_json(self, key: str) -> dict[str, Any] | None:
        client = await self._get_client()
        if client is None:
            return None
        try:
            raw = await client.get(key)
            return json.loads(raw) if raw else None
        except Exception as exc:
            logger.warning("RedisMarketCache.get_json error: {}", exc)
            return None

    async def push_list_json(self, key: str, data: dict[str, Any], max_length: int = 50, ttl: int = TTL_ALERT) -> bool:
        """Push a JSON item to the head of a Redis list, trim to max_length."""
        client = await self._get_client()
        if client is None:
            return False
        try:
            pipe = client.pipeline()
            pipe.lpush(key, json.dumps(data, default=str))
            pipe.ltrim(key, 0, max_length - 1)
            pipe.expire(key, ttl)
            await pipe.execute()
            return True
        except Exception as exc:
            logger.warning("RedisMarketCache.push_list_json error: {}", exc)
            return False

    async def get_list_json(self, key: str, count: int = 20) -> list[dict[str, Any]]:
        client = await self._get_client()
        if client is None:
            return []
        try:
            items = await client.lrange(key, 0, count - 1)
            return [json.loads(item) for item in items if item]
        except Exception as exc:
            logger.warning("RedisMarketCache.get_list_json error: {}", exc)
            return []

    async def is_healthy(self) -> bool:
        client = await self._get_client()
        if client is None:
            return False
        try:
            return await client.ping()
        except Exception as exc:
            logger.warning("RedisMarketCache.is_healthy error: {}", exc)
            return False

    # ─── Domain helpers ───────────────────────────────────────────────────

    async def update_arabica(self, price: float, change_percent: float, volume: int | None = None) -> bool:
        data = {
            "arabica_price": price,
            "change_percent": change_percent,
            "volume": volume,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return await self.set_json(KEY_ARABICA, data, TTL_PRICE)

    async def update_robusta(self, price: float, change_percent: float, volume: int | None = None) -> bool:
        data = {
            "robusta_price": price,
            "change_percent": change_percent,
            "volume": volume,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return await self.set_json(KEY_ROBUSTA, data, TTL_PRICE)

    async def update_volatility(self, arabica_vol: float, robusta_vol: float) -> bool:
        data = {
            "arabica_volatility_pct": arabica_vol,
            "robusta_volatility_pct": robusta_vol,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        return await self.set_json(KEY_VOLATILITY, data, TTL_PRICE)

    async def update_market_state(self, state: dict[str, Any]) -> bool:
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        return await self.set_json(KEY_MARKET_STATE, state, TTL_PRICE)

    async def push_alert(self, alert: dict[str, Any]) -> bool:
        alert.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        return await self.push_list_json(KEY_ALERTS, alert, max_length=50, ttl=TTL_ALERT)

    async def push_spike(self, spike: dict[str, Any]) -> bool:
        spike.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        return await self.set_json(KEY_SPIKE_EVENT, spike, TTL_ALERT)

    # ─── Read helpers ─────────────────────────────────────────────────────

    async def get_arabica(self) -> dict[str, Any] | None:
        return await self.get_json(KEY_ARABICA)

    async def get_robusta(self) -> dict[str, Any] | None:
        return await self.get_json(KEY_ROBUSTA)

    async def get_volatility(self) -> dict[str, Any] | None:
        return await self.get_json(KEY_VOLATILITY)

    async def get_market_state(self) -> dict[str, Any] | None:
        return await self.get_json(KEY_MARKET_STATE)

    async def get_alerts(self, count: int = 10) -> list[dict[str, Any]]:
        return await self.get_list_json(KEY_ALERTS, count)

    async def get_latest_spike(self) -> dict[str, Any] | None:
        return await self.get_json(KEY_SPIKE_EVENT)

    async def get_live_snapshot(self) -> dict[str, Any]:
        """Return a combined live snapshot for chatbot hot-path."""
        arabica  = await self.get_arabica()
        robusta  = await self.get_robusta()
        vol      = await self.get_volatility()
        state    = await self.get_market_state()
        alerts   = await self.get_alerts(5)
        spike    = await self.get_latest_spike()
        return {
            "arabica":    arabica,
            "robusta":    robusta,
            "volatility": vol,
            "market_state": state,
            "recent_alerts": alerts,
            "latest_spike": spike,
            "snapshot_at": datetime.now(timezone.utc).isoformat(),
            "source": "redis_hot_cache",
        }

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as exc:
                logger.warning("RedisMarketCache.aclose error: {}", exc)
            self._client = None
