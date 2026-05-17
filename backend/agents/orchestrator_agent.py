"""
agents/orchestrator_agent.py
==============================
Thin orchestrator — coordinates intent classification, agent dispatch,
and response synthesis.

This file is intentionally SLIM (~130 lines).
All routing logic lives in  agents/routing/:
  • IntentRouter   — which agents to invoke given a set of intents
  • ToolSelector   — whether to use fast-path / agents / RAG

ADDING NEW AGENTS:
  1. Add the agent to __init__ and pass it in from core/runtime.py
  2. Add the agent's trigger intents to agents/routing/intent_router.py
  3. No changes needed here.

ADDING NEW ROUTING LOGIC:
  1. Edit agents/routing/tool_selector.py (decision tree)
  2. Or agents/routing/intent_router.py (dispatch table)
  3. No changes needed here.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from core.logger import bind_context
from core.errors import LLMError, RetrievalError
from agents.intent_classifier import IntentClassifier
from agents.routing.intent_router import IntentRouter
from agents.routing.tool_selector import ToolSelector
from streaming.redis_cache import RedisMarketCache

# ── Render constants (presentation layer) ─────────────────────────────────────
# Fix #11: emoji icons and Markdown formatting are declared here, at the module
# boundary, rather than hardcoded inside _synthesise() business logic.
# To change formatting: edit only this section, not the orchestration code.
_AGENT_ICONS: dict[str, str] = {
    "futures":  "\U0001f4c8",  # 📈
    "risk":     "\U0001f3af",  # 🎯
    "alert":    "\U0001f514",  # 🔔
    "forecast": "\U0001f52d",  # 🔭
    "weather":  "\U0001f326",  # 🌦
}
_RAG_SECTION_HEADER = "---\n\n**Intelligence Analysis:**\n\n"


class OrchestratorAgent:
    """
    Intelligent orchestrator — routes queries to specialized agents,
    merges intelligence layers, and composes actionable responses.

    HOT LAYER (Redis) → fast-path for live-price queries.
    Agent layer       → parallel specialized agent calls.
    COLD LAYER (RAG)  → depth and historical context from Qdrant.

    Intent routing: IntentRouter (dispatch table)
    Tool selection: ToolSelector (fast-path vs agents vs RAG vs hybrid)
    """

    def __init__(
        self,
        cache: RedisMarketCache | None = None,
        futures_agent=None,
        risk_agent=None,
        alert_agent=None,
        forecast_agent=None,
        chatbot_agent=None,
        weather_agent=None,
        intent_classifier: IntentClassifier | None = None,
    ) -> None:
        self._cache         = cache or RedisMarketCache()
        self._chatbot_agent = chatbot_agent
        self._classifier    = intent_classifier or IntentClassifier.instance()
        self._log           = bind_context(stream_id="orchestrator")

        # Build agent registry for router
        _agents = {
            "futures":  futures_agent,
            "risk":     risk_agent,
            "alert":    alert_agent,
            "forecast": forecast_agent,
            "weather":  weather_agent,
        }
        self._router   = IntentRouter(agents={k: v for k, v in _agents.items() if v is not None})
        self._selector = ToolSelector()

    # ── Public interface ──────────────────────────────────────────────────────

    async def answer(self, question: str, session_id: str, use_rag: bool = True) -> dict:
        """Main entry point — orchestrates agents and returns structured response."""
        intent = await self._classify_intent(question)
        self._log.info("OrchestratorAgent | intent={} q={!r:.60}", intent, question)

        plan = self._selector.select(
            question=question,
            intents=intent,
            use_rag=use_rag,
            has_chatbot=self._chatbot_agent is not None,
        )

        # ── Fast path ────────────────────────────────────────────────────────
        if plan.use_fast_path:
            live_answer = await self._live_price_answer(question)
            if live_answer:
                return live_answer

        # ── Agent dispatch ───────────────────────────────────────────────────
        agent_results: dict[str, Any] = {}
        if plan.use_agents:
            tasks_list = self._router.route(intent)
            if tasks_list:
                coros = [getattr(t.agent, t.method)(question) for t in tasks_list]
                done  = await asyncio.gather(*coros, return_exceptions=True)
                for task, result in zip(tasks_list, done):
                    if isinstance(result, Exception):
                        self._log.warning("Agent {} error: {}", task.name, result)
                    else:
                        agent_results[task.name] = result

        # ── RAG / LLM layer ──────────────────────────────────────────────────
        rag_response = None
        if plan.use_rag and self._chatbot_agent:
            try:
                rag_response = await self._chatbot_agent.answer(
                    question=question,
                    session_id=session_id,
                    use_rag=use_rag,
                )
            except (LLMError, RetrievalError) as exc:
                self._log.warning("RAG layer error: {}", exc)

        return self._synthesise(question, intent, agent_results, rag_response, session_id)

    # ── Intent classification ─────────────────────────────────────────────────

    async def _classify_intent(self, question: str) -> list[str]:
        return await self._classifier.classify_async(question)

    # ── Live price fast-path ──────────────────────────────────────────────────

    async def _live_price_answer(self, question: str) -> dict | None:
        snapshot = await self._cache.get_live_snapshot()
        arabica  = snapshot.get("arabica")
        robusta  = snapshot.get("robusta")
        if not arabica and not robusta:
            return None

        a_price  = float((arabica or {}).get("arabica_price") or 0)
        r_price  = float((robusta  or {}).get("robusta_price") or 0)
        a_change = float((arabica or {}).get("change_percent") or 0)
        r_change = float((robusta  or {}).get("change_percent") or 0)
        updated  = (arabica or robusta or {}).get("updated_at", "")

        parts = []
        if a_price > 0:
            parts.append(f"Arabica futures: {a_price:.2f} US cents/lb ({a_change:+.2f}%)")
        if r_price > 0:
            parts.append(f"Robusta: {r_price:.0f} USD/tonne ({r_change:+.2f}%)")
        if not parts:
            return None

        answer = (
            "**Live Coffee Market Prices** (Redis hot cache):\n\n"
            + "\n".join(f"• {p}" for p in parts)
            + (f"\n\n_Last updated: {updated}_" if updated else "")
        )
        return {
            "answer":         answer,
            "sources":        [],
            "session_id":     "",
            "model":          "redis_hot_cache",
            "provider":       "streaming_layer",
            "retrieval_mode": "live_redis",
            "agents_used":    ["futures_hot_cache"],
            "live_data":      snapshot,
            "generated_at":   datetime.now(timezone.utc).isoformat(),
        }

    # ── Response synthesis ────────────────────────────────────────────────────

    def _synthesise(
        self,
        question: str,
        intent: list[str],
        agent_results: dict,
        rag_response: Any,
        session_id: str,
    ) -> dict:
        # Fix #11: rendering uses module-level constants, not hardcoded literals
        blocks: list[str] = []
        for key, icon in _AGENT_ICONS.items():
            if key in agent_results:
                summary = agent_results[key].get("summary", "")
                if summary:
                    blocks.append(f"{icon} **{key.title()}**: {summary}")

        rag_text: str     = ""
        rag_sources: list = []
        rag_model: str    = ""
        if rag_response is not None:
            try:
                rag_text    = rag_response.answer  if hasattr(rag_response, "answer")  else str(rag_response)
                rag_sources = rag_response.sources if hasattr(rag_response, "sources") else []
                rag_model   = rag_response.model   if hasattr(rag_response, "model")   else ""
            except AttributeError as exc:
                self._log.warning("Failed to extract rag_response attributes: {}", exc)

        if blocks and rag_text:
            answer = "\n".join(blocks) + "\n\n" + _RAG_SECTION_HEADER + rag_text
        elif blocks:
            answer = "\n".join(blocks)
        elif rag_text:
            answer = rag_text
        else:
            answer = (
                "No real-time data or historical intelligence is available for this query. "
                "Please ensure the live stream and ingestion pipeline are running."
            )

        return {
            "answer":         answer,
            "sources":        rag_sources,
            "session_id":     session_id,
            "model":          rag_model or "orchestrator",
            "provider":       "orchestrator_agent",
            "retrieval_mode": "orchestrated",
            "intent":         intent,
            "agents_used":    list(agent_results.keys()) + (["rag"] if rag_text else []),
            "generated_at":   datetime.now(timezone.utc).isoformat(),
        }
