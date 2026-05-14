"""
streaming/dead_letter_queue.py
==============================
Enterprise Dead Letter Queue (DLQ). Captures malformed streaming payloads,
disconnection drops, and failed ingestion models to ensure operational transparency.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from core.logger import logger
from core.middleware import get_request_id, get_trace_id
from streaming.redis_cache import RedisMarketCache

KEY_DLQ_EVENTS = "coffee:dlq:events"
DLQ_MAX_LENGTH = 200


class DeadLetterQueue:
    """
    Asynchronous queue saving unparseable/failed event envelopes.
    Provides professional diagnostic tracing for integration pipelines.
    """

    def __init__(self, cache: RedisMarketCache | None = None) -> None:
        self._cache = cache or RedisMarketCache()

    async def push(
        self,
        event_type: str,
        payload: Any,
        error_message: str,
    ) -> bool:
        """
        Record a dead-letter item tagged with lifecycle Trace IDs and Request IDs.
        Silently degrades if storage layers are saturated or offline.
        """
        # Ensure payload is safely JSON serializable
        try:
            safe_payload = json.loads(json.dumps(payload, default=str)) if isinstance(payload, dict) else str(payload)
        except Exception:
            safe_payload = str(payload)

        envelope = {
            "event_type": event_type,
            "payload": safe_payload,
            "error_message": error_message,
            "request_id": get_request_id(),
            "trace_id": get_trace_id(),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            # TTL set to 30 days (2592000 seconds) to ensure long-term retentivity
            success = await self._cache.push_list_json(
                KEY_DLQ_EVENTS,
                envelope,
                max_length=DLQ_MAX_LENGTH,
                ttl=2592000,
            )
            if success:
                logger.info("DLQ item captured: event_type={} error={}", event_type, error_message)
            return success
        except Exception as exc:
            logger.debug("DLQ storage push failed: {}", exc)
            return False

    async def get_recent(self, count: int = 50) -> list[dict[str, Any]]:
        """Retrieve recent unhandled dead-letter anomalies for system inspection."""
        return await self._cache.get_list_json(KEY_DLQ_EVENTS, count=count)

    async def clear(self) -> bool:
        """Purge the dead-letter queue after manual intervention sweeps."""
        client = await self._cache._get_client()
        if client is None:
            return False
        try:
            await client.delete(KEY_DLQ_EVENTS)
            logger.info("Dead-letter queue purged successfully.")
            return True
        except Exception as exc:
            logger.warning("DLQ clear operation failed: {}", exc)
            return False
