"""
streaming/market_event_bus.py
=============================
Real-Time Market Event Bus. Establishes decoupled publish/subscribe broadcast
channels over Redis PubSub, supporting highly available hybrid local fallback routing.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis

from core.config import settings
from core.logger import logger
from core.middleware import get_request_id, get_trace_id

# ─── Allowed Broadcast Channels ─────────────────────────────────────────────
CHANNEL_FUTURES_UPDATED = "futures_updated"
CHANNEL_RISK_CHANGED    = "risk_changed"
CHANNEL_ALERT_GENERATED = "alert_generated"
CHANNEL_WEATHER_ALERT   = "weather_alert"

ALLOWED_CHANNELS = {
    CHANNEL_FUTURES_UPDATED,
    CHANNEL_RISK_CHANGED,
    CHANNEL_ALERT_GENERATED,
    CHANNEL_WEATHER_ALERT,
}


class MarketEventBus:
    """
    Decoupled Event Orchestrator. Dispatches domain payloads to subscribers
    across distributed server boundaries via Redis PubSub channels.
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._url = redis_url or settings.redis_url
        self._client: aioredis.Redis | None = None
        self._local_subscribers: dict[str, list[Callable[[dict[str, Any]], Awaitable[None]]]] = defaultdict(list)
        self._listener_tasks: dict[str, asyncio.Task] = {}
        self._running = False

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
            logger.debug("MarketEventBus: Redis unavailable, using local memory fallback loop ({})", exc)
            self._client = None
            return None

    def _prepare_envelope(self, channel: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Wrap outgoing raw domain message with consistent cluster tracing headers."""
        return {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "channel": channel,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": get_request_id(),
            "trace_id": get_trace_id(),
            "data": payload,
        }

    async def publish(self, channel: str, payload: dict[str, Any]) -> bool:
        """
        Broadcast structured message envelope over the specific topic channel.
        Always routes to active local memory subscriber hooks instantaneously.
        """
        if channel not in ALLOWED_CHANNELS:
            logger.warning("EventBus drop: invalid broadcast channel '{}'", channel)
            return False

        envelope = self._prepare_envelope(channel, payload)
        serialized = json.dumps(envelope, default=str)
        published_remote = False

        # 1. Attempt broadcast over shared cluster interface
        client = await self._get_client()
        if client is not None:
            try:
                await client.publish(f"coffee:broadcast:{channel}", serialized)
                published_remote = True
            except Exception as exc:
                logger.debug("Redis publish skipped, routing local only: {}", exc)

        # 2. Synchronous local dispatch fallback loop
        local_hooks = self._local_subscribers.get(channel, [])
        for hook in local_hooks:
            try:
                # Dispatch as background fire-and-forget subtask
                asyncio.create_task(hook(envelope))
            except Exception as exc:
                logger.error("Local subscriber hook fault on channel {}: {}", channel, exc)

        logger.debug("Published event {} | remote={} local_hooks={}", envelope["event_id"], published_remote, len(local_hooks))
        return True

    async def subscribe(self, channel: str, callback: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        """
        Register persistent listener targeting specific market channel broadcasts.
        Automatically spins up background PubSub task monitor loop if needed.
        """
        if channel not in ALLOWED_CHANNELS:
            raise ValueError(f"Unsupported subscription channel: {channel}")

        self._local_subscribers[channel].append(callback)
        logger.info("Registered subscriber hook for event bus topic: {}", channel)

        # Launch distributed topic adapter loop if not already present
        if channel not in self._listener_tasks or self._listener_tasks[channel].done():
            self._running = True
            self._listener_tasks[channel] = asyncio.create_task(self._redis_listener_loop(channel))

    async def _redis_listener_loop(self, channel: str) -> None:
        """Dedicated asyncio worker monitoring shared upstream Redis channel blocks."""
        topic = f"coffee:broadcast:{channel}"
        logger.debug("Starting Redis subscription daemon targeting topic: {}", topic)

        while self._running:
            client = await self._get_client()
            if client is None:
                # Cool down before retry scan
                await asyncio.sleep(5.0)
                continue

            pubsub = client.pubsub()
            try:
                await pubsub.subscribe(topic)
                async for message in pubsub.listen():
                    if not self._running:
                        break
                    if message["type"] == "message":
                        try:
                            envelope = json.loads(message["data"])
                            # Dispatch decoded envelope to registered consumers
                            for hook in self._local_subscribers.get(channel, []):
                                asyncio.create_task(hook(envelope))
                        except Exception as exc:
                            logger.warning("Malformed broadcast frame dropped on topic {}: {}", topic, exc)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Redis listener connection dropped on topic {}: {}", topic, exc)
                await asyncio.sleep(3.0)  # Reconnection pacing limiter
            finally:
                try:
                    await pubsub.unsubscribe(topic)
                    await pubsub.aclose()
                except Exception:
                    pass

    async def aclose(self) -> None:
        """Gracefully terminate background adapter listener routines."""
        self._running = False
        for task in self._listener_tasks.values():
            task.cancel()
        await asyncio.gather(*self._listener_tasks.values(), return_exceptions=True)
        self._listener_tasks.clear()

        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
