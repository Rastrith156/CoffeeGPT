"""
agents/orchestrator_agent.py
==============================
STEP 1 (Autonomous Phase) — Orchestrator Agent

The orchestrator decides which specialized agents to invoke,
collects their outputs, and synthesises a final coherent response.

Intent routing now uses the embedding-based IntentClassifier (Task 1)
instead of brittle keyword matching. Prototype vectors are pre-warmed
in Redis at startup — classify() runs in < 2 ms per query.

Fallback: if no intent scores >= 0.35 → routes to "general" (RAG-only).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from core.logger import logger
from agents.intent_classifier import IntentClassifier
from streaming.redis_cache import RedisMarketCache


class OrchestratorAgent:
    """
    Intelligent orchestrator — routes queries to specialized agents,
    merges intelligence layers, and composes actionable responses.

    HOT LAYER (Redis) is consulted FIRST for real-time questions.
    COLD LAYER (RAG/Qdrant) is used for depth and historical context.

    Intent routing is performed by IntentClassifier (embedding cosine-similarity).
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
        self._cache          = cache or RedisMarketCache()
        self._futures_agent  = futures_agent
        self._risk_agent     = risk_agent
        self._alert_agent    = alert_agent
        self._forecast_agent = forecast_agent
        self._chatbot_agent  = chatbot_agent
        self._weather_agent  = weather_agent
        # Use provided classifier or shared singleton (warm-up must have run)
        self._classifier: IntentClassifier = intent_classifier or IntentClassifier.instance()

    # ─── Public interface ────────────────────────────────────────────────────

    async def answer(self, question: str, session_id: str, use_rag: bool = True) -> dict:
        """
        Main entry point — orchestrates agents and returns structured response.
        """
        intent = await self._classify_intent(question)
        logger.info("OrchestratorAgent | intent={} question={!r:.60}", intent, question)

        # ── Live price fast-path ─────────────────────────────────────────────
        if "live_price" in intent and not any(k in intent for k in ("risk", "forecast")):
            live_answer = await self._live_price_answer(question)
            if live_answer:
                return live_answer

        # ── Gather relevant agent outputs in parallel ────────────────────────
        tasks: dict[str, asyncio.Task] = {}
        if self._futures_agent and ("live_price" in intent or "risk" in intent or "forecast" in intent):
            tasks["futures"] = asyncio.create_task(self._futures_agent.analyze(question))
        if self._risk_agent and ("risk" in intent or "alert" in intent):
            tasks["risk"] = asyncio.create_task(self._risk_agent.analyze(question))
        if self._alert_agent and ("alert" in intent or "risk" in intent):
            tasks["alert"] = asyncio.create_task(self._alert_agent.analyze(question))
        if self._forecast_agent and ("forecast" in intent or "risk" in intent):
            tasks["forecast"] = asyncio.create_task(self._forecast_agent.analyze(question))
        if self._weather_agent and "weather" in intent:
            tasks["weather"] = asyncio.create_task(self._weather_agent.analyze(question))
        # General intent — chatbot-only, already handled in RAG layer below

        agent_results: dict[str, Any] = {}
        if tasks:
            done = await asyncio.gather(*tasks.values(), return_exceptions=True)
            for key, result in zip(tasks.keys(), done):
                if isinstance(result, Exception):
                    logger.warning("OrchestratorAgent: {} agent error: {}", key, result)
                else:
                    agent_results[key] = result

        # ── RAG / LLM layer ─────────────────────────────────────────────────
        rag_response = None
        if use_rag and self._chatbot_agent:
            try:
                rag_response = await self._chatbot_agent.answer(
                    question=question,
                    session_id=session_id,
                    use_rag=use_rag,
                )
            except Exception as exc:
                logger.warning("OrchestratorAgent: RAG layer error: {}", exc)

        # ── Synthesise final response ────────────────────────────────────────
        return self._synthesise(
            question=question,
            intent=intent,
            agent_results=agent_results,
            rag_response=rag_response,
            session_id=session_id,
        )

    # ─── Intent classification (Task 1) ──────────────────────────────────────

    async def _classify_intent(self, question: str) -> list[str]:
        """
        Embed query and compare against Redis-cached prototype vectors.
        Runs inference in a thread-pool executor to avoid blocking event loop.
        Falls back to ["general"] if similarity < 0.35 for all intents.
        """
        return await self._classifier.classify_async(question)

    # ─── Live price fast-path ────────────────────────────────────────────────

    async def _live_price_answer(self, question: str) -> dict | None:
        """Short-circuit to Redis data for pure live-price queries."""
        snapshot = await self._cache.get_live_snapshot()
        arabica  = snapshot.get("arabica")
        robusta  = snapshot.get("robusta")
        if not arabica and not robusta:
            return None

        a_price  = float((arabica or {}).get("arabica_price") or 0)
        r_price  = float((robusta or {}).get("robusta_price") or 0)
        a_change = float((arabica or {}).get("change_percent") or 0)
        r_change = float((robusta or {}).get("change_percent") or 0)
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
            "answer": answer,
            "sources": [],
            "session_id": "",
            "model": "redis_hot_cache",
            "provider": "streaming_layer",
            "retrieval_mode": "live_redis",
            "agents_used": ["futures_hot_cache"],
            "live_data": snapshot,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ─── Synthesis ───────────────────────────────────────────────────────────

    def _synthesise(
        self,
        question: str,
        intent: list[str],
        agent_results: dict,
        rag_response,
        session_id: str,
    ) -> dict:
        intelligence_blocks: list[str] = []

        if "futures" in agent_results:
            fut = agent_results["futures"]
            if fut.get("summary"):
                intelligence_blocks.append(f"📈 **Futures**: {fut['summary']}")

        if "risk" in agent_results:
            risk = agent_results["risk"]
            if risk.get("summary"):
                intelligence_blocks.append(f"🎯 **Risk**: {risk['summary']}")

        if "alert" in agent_results:
            alrt = agent_results["alert"]
            if alrt.get("summary"):
                intelligence_blocks.append(f"🔔 **Alerts**: {alrt['summary']}")

        if "forecast" in agent_results:
            fcast = agent_results["forecast"]
            if fcast.get("summary"):
                intelligence_blocks.append(f"🔭 **Outlook**: {fcast['summary']}")

        if "weather" in agent_results:
            w = agent_results["weather"]
            if w.get("summary"):
                intelligence_blocks.append(f"🌦 **Weather**: {w['summary']}")

        rag_text  = ""
        rag_sources = []
        rag_model = ""
        if rag_response is not None:
            try:
                rag_text    = rag_response.answer if hasattr(rag_response, "answer") else str(rag_response)
                rag_sources = rag_response.sources if hasattr(rag_response, "sources") else []
                rag_model   = rag_response.model   if hasattr(rag_response, "model") else ""
            except Exception as exc:
                logger.warning("Failed to extract rag_response attributes: {}", exc)
                rag_text = ""

        if intelligence_blocks and rag_text:
            answer = (
                "\n".join(intelligence_blocks)
                + "\n\n---\n\n**Intelligence Analysis:**\n\n"
                + rag_text
            )
        elif intelligence_blocks:
            answer = "\n".join(intelligence_blocks)
        elif rag_text:
            answer = rag_text
        else:
            answer = (
                "No real-time data or historical intelligence is available for this query. "
                "Please ensure the live stream and ingestion pipeline are running."
            )

        return {
            "answer": answer,
            "sources": rag_sources,
            "session_id": session_id,
            "model": rag_model or "orchestrator",
            "provider": "orchestrator_agent",
            "retrieval_mode": "orchestrated",
            "intent": intent,
            "agents_used": list(agent_results.keys()) + (["rag"] if rag_text else []),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
