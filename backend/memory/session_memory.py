"""
memory/session_memory.py
=========================
STEP 3 (Autonomous Phase) — Conversation Session Memory

Stores per-session conversation history and market context in Redis.
Enables persistent, intelligent multi-turn conversations.

Redis key: coffee:session:<session_id>  (TTL: 24h)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as aioredis

from core.config import settings
from core.logger import logger

SESSION_TTL_SECONDS = 86_400   # 24 hours
MAX_HISTORY_MESSAGES = 20      # keep last 20 exchange pairs


class SessionMemory:
    """
    Redis-backed session memory for multi-turn chatbot conversations.

    Stores:
      - conversation history (role / content pairs)
      - last market snapshot seen by the user
      - prior recommendations
      - session metadata
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
                socket_connect_timeout=3,
                socket_timeout=3,
            )
            await self._client.ping()
            return self._client
        except Exception as exc:
            logger.warning("SessionMemory: Redis unavailable ({})", exc)
            self._client = None
            return None

    # ─── Key helpers ─────────────────────────────────────────────────────────

    def _key(self, session_id: str) -> str:
        return f"coffee:session:{session_id}"

    # ─── Read / Write ─────────────────────────────────────────────────────────

    async def load(self, session_id: str) -> dict[str, Any]:
        """Load full session object. Returns empty session if not found."""
        client = await self._get_client()
        if client is None:
            return self._empty_session(session_id)
        try:
            raw = await client.get(self._key(session_id))
            if raw:
                return json.loads(raw)
        except Exception as exc:
            logger.warning("SessionMemory.load error: {}", exc)
        return self._empty_session(session_id)

    async def save(self, session_id: str, session: dict[str, Any]) -> bool:
        client = await self._get_client()
        if client is None:
            return False
        try:
            session["updated_at"] = datetime.now(timezone.utc).isoformat()
            await client.setex(
                self._key(session_id),
                SESSION_TTL_SECONDS,
                json.dumps(session, default=str),
            )
            return True
        except Exception as exc:
            logger.warning("SessionMemory.save error: {}", exc)
            return False

    async def append_exchange(
        self,
        session_id: str,
        user_message: str,
        assistant_message: str,
        market_snapshot: dict[str, Any] | None = None,
    ) -> None:
        """Append a Q/A pair to the session history."""
        session = await self.load(session_id)
        history: list[dict] = session.get("history", [])

        history.append({
            "role": "user",
            "content": user_message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        history.append({
            "role": "assistant",
            "content": assistant_message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Trim to max window
        if len(history) > MAX_HISTORY_MESSAGES * 2:
            history = history[-(MAX_HISTORY_MESSAGES * 2):]

        session["history"] = history
        session["message_count"] = session.get("message_count", 0) + 1

        if market_snapshot:
            session["last_market_snapshot"] = market_snapshot

        await self.save(session_id, session)

    async def get_history(self, session_id: str) -> list[dict[str, Any]]:
        session = await self.load(session_id)
        return session.get("history", [])

    async def get_last_recommendation(self, session_id: str) -> str | None:
        session = await self.load(session_id)
        history = session.get("history", [])
        for item in reversed(history):
            if item.get("role") == "assistant":
                return item.get("content")
        return None

    async def get_last_market_snapshot(self, session_id: str) -> dict[str, Any] | None:
        session = await self.load(session_id)
        return session.get("last_market_snapshot")

    async def build_context_summary(self, session_id: str) -> str:
        """Build a short prior-context string to prepend to new LLM prompts."""
        session = await self.load(session_id)
        history = session.get("history", [])
        if not history:
            return ""

        recent = history[-6:]   # last 3 pairs
        lines = ["Prior conversation context:"]
        for item in recent:
            role = "User" if item["role"] == "user" else "CoffeeGPT"
            content = str(item.get("content", ""))[:200]
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    async def delete(self, session_id: str) -> bool:
        client = await self._get_client()
        if client is None:
            return False
        try:
            await client.delete(self._key(session_id))
            return True
        except Exception as exc:
            logger.warning("SessionMemory.delete error: {}", exc)
            return False

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception as exc:
                logger.warning("SessionMemory.aclose error: {}", exc)
            self._client = None

    # ─── Factory ─────────────────────────────────────────────────────────────

    def _empty_session(self, session_id: str) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "history": [],
            "message_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_market_snapshot": None,
        }
