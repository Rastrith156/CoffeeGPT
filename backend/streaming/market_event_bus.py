"""
streaming/market_event_bus.py
==============================
ISSUE #7 FIX — Production-grade market event bus.

Improvements over the previous version:
  ✅ Subscriber isolation   — each hook is called in its own try/except;
                              one bad subscriber never blocks others.
  ✅ Dead-letter queue      — failed critical events are persisted to the DLQ.
  ✅ In-memory retry queue  — publish failures are enqueued for async retry
                              (capped deque, background retry task).
  ✅ Structured envelope    — event_id, channel, timestamp, payload_version,
                              correlation_id, request_id, trace_id.
  ✅ Typed errors           — RedisError / StreamingError instead of bare Exception.
  ✅ Exponential backoff    — retry task backs off on repeated Redis failures.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis

from core.config import settings
from core.errors import RedisError, StreamingError
from core.logger import logger
from core.middleware import get_request_id, get_trace_id

# ── Allowed broadcast channels ────────────────────────────────────────────────
CHANNEL_FUTURES_UPDATED = "futures_updated"
CHANNEL_RISK_CHANGED    = "risk_changed"
CHANNEL_ALERT_GENERATED = "alert_generated"
CHANNEL_WEATHER_ALERT   = "weather_alert"

ALLOWED_CHANNELS: frozenset[str] = frozenset({
    CHANNEL_FUTURES_UPDATED,
    CHANNEL_RISK_CHANGED,
    CHANNEL_ALERT_GENERATED,
    CHANNEL_WEATHER_ALERT,
})

# Critical channels whose failures trigger DLQ persistence
CRITICAL_CHANNELS: frozenset[str] = frozenset({
    CHANNEL_RISK_CHANGED,
    CHANNEL_ALERT_GENERATED,
})

# Payload schema version — bump on breaking envelope changes
_PAYLOAD_VERSION = "1.1"

# Retry queue configuration
_MAX_RETRY_QUEUE: int = 200          # max in-memory items
_RETRY_BASE_BACKOFF_S: float = 2.0   # initial retry backoff
_RETRY_MAX_BACKOFF_S: float = 120.0  # cap retry backoff
_RETRY_MAX_ATTEMPTS: int = 5         # per-event retry ceiling

# Subscriber timeout — a single hook call that hangs this long is abandoned
_SUBSCRIBER_TIMEOUT_S: float = 5.0


class MarketEventBus:
    """
    Decoupled market event bus with Redis PubSub + in-process fallback.

    Architecture:
      publish(channel, payload)
        ├─▶ Redis PUBLISH (remote broadcast)
        ├─▶ local subscribers (isolated, per-hook try/except)
        └─▶ on failure → retry queue + DLQ (critical channels)

    subscribe(channel, callback)
        ├─▶ registers local in-process hook
        └─▶ starts background Redis PubSub listener (if not already running)
    """

    def __init__(self, redis_url: str | None = None) -> None:
        self._url = redis_url or settings.redis_url
        self._client: aioredis.Redis | None = None
        self._local_subscribers: dict[
            str, list[Callable[[dict[str, Any]], Awaitable[None]]]
        ] = defaultdict(list)
        self._listener_tasks: dict[str, asyncio.Task] = {}
        self._running = False

        # ── Retry infrastructure ──────────────────────────────────────────────
        # Each item: {"envelope": dict, "channel": str, "attempts": int}
        self._retry_queue: deque[dict[str, Any]] = deque(maxlen=_MAX_RETRY_QUEUE)
        self._retry_task: asyncio.Task | None = None
        self._retry_consecutive_failures: int = 0

    # ── Connection ────────────────────────────────────────────────────────────

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
        except RedisError:
            self._client = None
            raise
        except Exception as exc:
            logger.debug("MarketEventBus: Redis unavailable → local fallback ({})", exc)
            self._client = None
            return None

    # ── Envelope construction ─────────────────────────────────────────────────

    def _build_envelope(
        self,
        channel: str,
        payload: dict[str, Any],
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """Build a strongly-typed event envelope."""
        return {
            "event_id":       f"evt_{uuid.uuid4().hex}",
            "channel":        channel,
            "payload_version": _PAYLOAD_VERSION,
            "timestamp":      datetime.now(timezone.utc).isoformat(),
            "request_id":     get_request_id(),
            "trace_id":       get_trace_id(),
            "correlation_id": correlation_id or f"corr_{uuid.uuid4().hex[:8]}",
            "data":           payload,
        }

    # ── Publish ───────────────────────────────────────────────────────────────

    async def publish(
        self,
        channel: str,
        payload: dict[str, Any],
        *,
        correlation_id: str | None = None,
    ) -> bool:
        """
        Broadcast a structured event envelope.

        1. Build envelope with tracing headers.
        2. Attempt Redis PUBLISH.
        3. Dispatch to all local subscribers (isolated per-hook).
        4. On Redis failure: enqueue for retry + DLQ for critical channels.

        Returns True if the event was delivered to at least one destination.
        """
        if channel not in ALLOWED_CHANNELS:
            logger.warning("EventBus drop: invalid channel '{}'", channel)
            return False

        envelope = self._build_envelope(channel, payload, correlation_id)
        serialized = json.dumps(envelope, default=str)
        published_remote = False

        # ── 1. Redis broadcast ────────────────────────────────────────────────
        client = await self._get_client()
        if client is not None:
            try:
                await client.publish(f"coffee:broadcast:{channel}", serialized)
                published_remote = True
                self._retry_consecutive_failures = 0
            except RedisError as exc:
                logger.warning("EventBus Redis publish failed: {}", exc)
                self._client = None
                self._enqueue_retry(channel, envelope)
            except Exception as exc:
                logger.debug("EventBus Redis publish skipped: {}", exc)
                self._client = None
                self._enqueue_retry(channel, envelope)
        else:
            # Redis not available — queue for retry
            self._enqueue_retry(channel, envelope)

        # ── 2. DLQ for critical channels on Redis failure ─────────────────────
        if not published_remote and channel in CRITICAL_CHANNELS:
            asyncio.create_task(self._persist_to_dlq(channel, envelope))

        # ── 3. Local subscriber dispatch (isolated) ───────────────────────────
        local_hooks = list(self._local_subscribers.get(channel, []))
        dispatched_local = 0
        for hook in local_hooks:
            success = await self._safe_dispatch(hook, envelope, channel)
            if success:
                dispatched_local += 1

        logger.debug(
            "EventBus published | event_id={} channel={} remote={} local={}/{}",
            envelope["event_id"],
            channel,
            published_remote,
            dispatched_local,
            len(local_hooks),
        )
        return published_remote or dispatched_local > 0

    # ── Subscriber dispatch (isolated) ────────────────────────────────────────

    async def _safe_dispatch(
        self,
        hook: Callable[[dict[str, Any]], Awaitable[None]],
        envelope: dict[str, Any],
        channel: str,
    ) -> bool:
        """
        Invoke a single subscriber hook in complete isolation.

        A failing or timing-out hook NEVER crashes publish() or blocks others.
        Returns True on success, False on failure.
        """
        try:
            await asyncio.wait_for(
                asyncio.create_task(hook(envelope)),
                timeout=_SUBSCRIBER_TIMEOUT_S,
            )
            return True
        except asyncio.TimeoutError:
            logger.warning(
                "EventBus subscriber timeout on channel {} ({}s)",
                channel, _SUBSCRIBER_TIMEOUT_S,
            )
            return False
        except asyncio.CancelledError:
            raise  # propagate cancellation upward — do not swallow
        except Exception as exc:
            logger.error(
                "EventBus subscriber error on channel {}: {}", channel, exc
            )
            return False

    # ── Subscribe ─────────────────────────────────────────────────────────────

    async def subscribe(
        self,
        channel: str,
        callback: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        """Register a local subscriber hook and start Redis listener if needed."""
        if channel not in ALLOWED_CHANNELS:
            raise StreamingError(
                f"Unsupported subscription channel: {channel}",
                context={"allowed": list(ALLOWED_CHANNELS)},
            )
        self._local_subscribers[channel].append(callback)
        logger.info("EventBus: registered subscriber on channel '{}'", channel)

        if channel not in self._listener_tasks or self._listener_tasks[channel].done():
            self._running = True
            self._listener_tasks[channel] = asyncio.create_task(
                self._redis_listener_loop(channel),
                name=f"event_bus_listener_{channel}",
            )

        # Start retry task once on first subscription
        if self._retry_task is None or self._retry_task.done():
            self._retry_task = asyncio.create_task(
                self._retry_loop(),
                name="event_bus_retry_loop",
            )

    # ── Redis listener loop ────────────────────────────────────────────────────

    async def _redis_listener_loop(self, channel: str) -> None:
        """Background task — listens on Redis PubSub and dispatches to local hooks."""
        topic = f"coffee:broadcast:{channel}"
        logger.debug("EventBus: starting Redis listener for '{}'", topic)

        while self._running:
            client = await self._get_client()
            if client is None:
                await asyncio.sleep(5.0)
                continue

            pubsub = client.pubsub()
            try:
                await pubsub.subscribe(topic)
                async for message in pubsub.listen():
                    if not self._running:
                        break
                    if message.get("type") != "message":
                        continue
                    try:
                        raw_envelope = json.loads(message["data"])
                    except (json.JSONDecodeError, KeyError) as exc:
                        logger.warning(
                            "EventBus: malformed message on '{}': {}", topic, exc
                        )
                        continue
                    # Dispatch to all local hooks (isolated)
                    for hook in list(self._local_subscribers.get(channel, [])):
                        await self._safe_dispatch(hook, raw_envelope, channel)
            except asyncio.CancelledError:
                break
            except RedisError as exc:
                logger.warning(
                    "EventBus: Redis listener connection error on '{}': {}", topic, exc
                )
                self._client = None
                await asyncio.sleep(3.0)
            except Exception as exc:
                logger.debug(
                    "EventBus: listener loop error on '{}': {}", topic, exc
                )
                self._client = None
                await asyncio.sleep(3.0)
            finally:
                try:
                    await pubsub.unsubscribe(topic)
                    await pubsub.aclose()
                except Exception:
                    pass

    # ── Retry queue ───────────────────────────────────────────────────────────

    def _enqueue_retry(self, channel: str, envelope: dict[str, Any]) -> None:
        """Push a failed event onto the in-memory retry queue."""
        self._retry_queue.append({
            "channel":  channel,
            "envelope": envelope,
            "attempts": 0,
        })

    async def _retry_loop(self) -> None:
        """
        Background task — retries failed Redis publishes with exponential backoff.
        Drops events that exceed _RETRY_MAX_ATTEMPTS.
        """
        logger.debug("EventBus: retry loop started")
        while self._running:
            await asyncio.sleep(1.0)
            if not self._retry_queue:
                continue

            item = self._retry_queue.popleft()
            channel  = item["channel"]
            envelope = item["envelope"]
            attempts = item["attempts"] + 1

            client = await self._get_client()
            if client is None:
                self._retry_consecutive_failures += 1
                backoff = min(
                    _RETRY_BASE_BACKOFF_S * (2 ** min(self._retry_consecutive_failures, 6)),
                    _RETRY_MAX_BACKOFF_S,
                )
                logger.debug(
                    "EventBus retry: Redis still unavailable — backing off {:.1f}s", backoff
                )
                if attempts <= _RETRY_MAX_ATTEMPTS:
                    item["attempts"] = attempts
                    self._retry_queue.appendleft(item)
                await asyncio.sleep(backoff)
                continue

            try:
                serialized = json.dumps(envelope, default=str)
                await client.publish(f"coffee:broadcast:{channel}", serialized)
                self._retry_consecutive_failures = 0
                logger.info(
                    "EventBus retry succeeded | event_id={} channel={} attempt={}",
                    envelope.get("event_id"), channel, attempts,
                )
            except Exception as exc:
                logger.debug(
                    "EventBus retry failed (attempt {}/{}): {}", attempts, _RETRY_MAX_ATTEMPTS, exc
                )
                self._client = None
                if attempts < _RETRY_MAX_ATTEMPTS:
                    item["attempts"] = attempts
                    self._retry_queue.append(item)
                else:
                    logger.error(
                        "EventBus: event dropped after {} attempts | event_id={} channel={}",
                        _RETRY_MAX_ATTEMPTS, envelope.get("event_id"), channel,
                    )

    # ── DLQ persistence ───────────────────────────────────────────────────────

    async def _persist_to_dlq(self, channel: str, envelope: dict[str, Any]) -> None:
        """Persist critical failed events to the Dead Letter Queue."""
        try:
            from streaming.dead_letter_queue import DeadLetterQueue
            dlq = DeadLetterQueue()
            await dlq.push(
                event_type=channel,
                payload=envelope,
                error_message=f"Redis publish failed for critical channel '{channel}'",
            )
        except Exception as exc:
            logger.debug("EventBus: DLQ persistence failed: {}", exc)

    # ── Shutdown ──────────────────────────────────────────────────────────────

    async def aclose(self) -> None:
        """Gracefully shut down all listener and retry tasks."""
        self._running = False

        tasks = list(self._listener_tasks.values())
        if self._retry_task and not self._retry_task.done():
            tasks.append(self._retry_task)

        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._listener_tasks.clear()

        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

        logger.debug("MarketEventBus: closed cleanly")
