"""
agents/chatbot/context_assembler.py
=====================================
ISSUE #3 FIX — Redis hot-layer live context assembly.

Responsibilities:
  - Read live market state from Redis hot cache
  - Format it as a structured context prefix for the LLM
  - Fail gracefully when Redis is unavailable (return empty string)

Used by CoffeeChatbotAgent.answer() to prepend real-time price data
before the RAG context for recency-sensitive queries.
"""
from __future__ import annotations

from typing import Any

from core.logger import logger


# ── Recency query keywords ─────────────────────────────────────────────────────
_RECENCY_KEYWORDS: tuple[str, ...] = (
    "today", "latest", "recent", "currently",
    "now", "this week", "yesterday",
)


class ContextAssembler:
    """
    Assembles the live Redis hot-layer context prefix for time-sensitive queries.

    Injected into CoffeeChatbotAgent so it can be easily mocked in tests
    without actually needing a live Redis connection.
    """

    def __init__(self, cache=None) -> None:
        self._cache = cache  # RedisMarketCache | None

    # ── Public API ─────────────────────────────────────────────────────────────

    async def get_live_prefix(self, question: str) -> str:
        """
        Return a formatted live market state string to prepend to RAG context.

        Returns empty string if:
          - Cache is not configured
          - Question is not recency-sensitive
          - Redis has no price data
          - Redis is unavailable (graceful degradation)
        """
        if self._cache is None:
            return ""
        if not self._is_recency_question(question):
            return ""

        try:
            snapshot: dict[str, Any] = await self._cache.get_live_snapshot()
            arabica  = snapshot.get("arabica") or {}
            robusta  = snapshot.get("robusta") or {}
            risk     = await self._cache.get_json("coffee:live:risk") or {}
            spike    = snapshot.get("latest_spike")

            a_price = float(arabica.get("arabica_price") or 0)
            r_price = float(robusta.get("robusta_price") or 0)

            if a_price <= 0 and r_price <= 0:
                return ""

            lines: list[str] = [
                "[LIVE MARKET STATE — Redis hot cache]",
                "source: redis_stream",
                "type: live_market_snapshot",
            ]

            if a_price > 0:
                a_change = float(arabica.get("change_percent") or 0)
                lines.append(
                    f"arabica_price: {a_price:.2f} US cents/lb ({a_change:+.2f}%)"
                )

            if r_price > 0:
                r_change = float(robusta.get("change_percent") or 0)
                lines.append(
                    f"robusta_price: {r_price:.0f} USD/tonne ({r_change:+.2f}%)"
                )

            if risk:
                risk_level = risk.get("risk_level", "unknown")
                risk_score = float(risk.get("risk_score") or 0)
                lines.append(
                    f"market_risk: {risk_level} (score {risk_score:.0f}/100)"
                )
                rec = risk.get("recommendation", "")
                if rec:
                    lines.append(f"recommendation: {rec}")

            if spike:
                spike_msg = spike.get("message", "")
                if spike_msg:
                    lines.append(f"latest_spike: {spike_msg}")

            snapshot_at = snapshot.get("snapshot_at", "")
            if snapshot_at:
                lines.append(f"updated_at: {snapshot_at}")

            return "\n".join(lines)

        except Exception as exc:
            logger.debug(
                "ContextAssembler: live prefix fetch failed (non-critical): {}", exc
            )
            return ""

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _is_recency_question(question: str) -> bool:
        lowered = question.lower()
        return any(kw in lowered for kw in _RECENCY_KEYWORDS)
