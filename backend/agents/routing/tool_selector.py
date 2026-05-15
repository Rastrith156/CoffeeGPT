"""
agents/routing/tool_selector.py
================================
Tool selector — decides which intelligence layers to activate.

Responsibility:
  ✅ Decide: use RAG/LLM? use live Redis fast-path? agents only?
  ✅ Compose a ToolPlan describing what the orchestrator should execute
  ❌ Does NOT classify text (IntentClassifier)
  ❌ Does NOT dispatch agents (OrchestratorAgent)
  ❌ Does NOT route to specific agents (IntentRouter)

Decision logic:
  • "live_price" intent alone → fast-path (Redis only, skip LLM)
  • "general" intent only → RAG/LLM only
  • Mixed intents → full orchestration (agents + RAG)
  • RAG always disabled when: use_rag=False or no chatbot_agent

Usage:
    selector = ToolSelector()
    plan = selector.select(
        question="What is the arabica price?",
        intents=["live_price"],
        use_rag=True,
        has_chatbot=True,
    )
    # → ToolPlan(use_fast_path=True, use_rag=False, use_agents=False)
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolPlan:
    """
    Execution plan produced by ToolSelector.

    Fields:
        use_fast_path: True → short-circuit to Redis hot cache immediately
                       (no agents, no LLM — lowest latency path)
        use_agents:    True → dispatch specialized agents in parallel
        use_rag:       True → call chatbot_agent for LLM + RAG synthesis
    """
    use_fast_path: bool
    use_agents:    bool
    use_rag:       bool
    rationale:     str  # human-readable explanation (useful for debugging)


# Intents that are RAG-heavy (need deep historical context)
_RAG_HEAVY_INTENTS  = {"general", "weather", "forecast"}

# Intents that NEVER need RAG (real-time data only)
_REALTIME_ONLY_INTENTS = {"live_price", "alert"}

# Intents that benefit from agent data AND RAG synthesis
_HYBRID_INTENTS = {"risk", "forecast"}


class ToolSelector:
    """
    Stateless tool selector.  Determines the execution plan for a query.

    All decisions are deterministic and testable without any external
    dependencies (no LLM, no Redis, no DB).
    """

    def select(
        self,
        question: str,
        intents: list[str],
        use_rag: bool = True,
        has_chatbot: bool = True,
    ) -> ToolPlan:
        """
        Produce a ToolPlan given the classified intents and availability flags.

        Args:
            question:    The original user question (used for length heuristic).
            intents:     Classified intent labels from IntentClassifier.
            use_rag:     Whether RAG is globally enabled (from request param).
            has_chatbot: Whether a chatbot_agent is wired into the orchestrator.

        Returns:
            ToolPlan describing what to execute.
        """
        intent_set = set(intents)
        rag_available = use_rag and has_chatbot

        # ── Fast path: pure live-price query with no risk/forecast mix ────────
        if (
            "live_price" in intent_set
            and not (intent_set & {"risk", "forecast", "general"})
        ):
            return ToolPlan(
                use_fast_path=True,
                use_agents=False,
                use_rag=False,
                rationale="Pure live-price intent → Redis fast-path (no LLM)",
            )

        # ── General / conversational: RAG only ────────────────────────────────
        if intent_set == {"general"} or not (intent_set - {"general"}):
            return ToolPlan(
                use_fast_path=False,
                use_agents=False,
                use_rag=rag_available,
                rationale="General intent → RAG/LLM only",
            )

        # ── Real-time alerts only: agents only, no RAG ────────────────────────
        if intent_set <= _REALTIME_ONLY_INTENTS:
            return ToolPlan(
                use_fast_path=False,
                use_agents=True,
                use_rag=False,
                rationale="Real-time only intents → agents only, skip RAG",
            )

        # ── Hybrid: agents + RAG for deep synthesis ───────────────────────────
        return ToolPlan(
            use_fast_path=False,
            use_agents=True,
            use_rag=rag_available,
            rationale=f"Hybrid intents {sorted(intent_set)} → agents + RAG synthesis",
        )

    def explain(self, intents: list[str], use_rag: bool = True, has_chatbot: bool = True) -> str:
        """Return a human-readable explanation of the plan for a given intent set."""
        plan = self.select(question="", intents=intents, use_rag=use_rag, has_chatbot=has_chatbot)
        return (
            f"intents={sorted(intents)} → "
            f"fast_path={plan.use_fast_path} agents={plan.use_agents} rag={plan.use_rag} "
            f"| {plan.rationale}"
        )
