"""
agents/routing/intent_router.py
================================
Intent router — maps classified intents to a list of AgentTask descriptors.

Responsibility:
  ✅ Decide WHICH agents should be invoked given a set of intent labels
  ✅ Define priority ordering (futures > risk > alert > forecast > weather)
  ✅ Enforce agent availability (skip if agent not wired)
  ❌ Does NOT classify text → intents (that is IntentClassifier's job)
  ❌ Does NOT invoke agents (that is OrchestratorAgent's job)
  ❌ Does NOT decide whether to use RAG (that is ToolSelector's job)

This separation means the dispatch table can be unit-tested independently
and updated without touching the orchestrator or the LLM layer.

Usage:
    router = IntentRouter(agents={...})
    tasks  = router.route(intents=["risk", "live_price"])
    # tasks = [AgentTask("futures", ...), AgentTask("risk", ...)]
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentTask:
    """Descriptor for one agent call to be dispatched by the orchestrator."""
    name:    str   # human-readable key ("futures", "risk", etc.)
    agent:   Any   # the actual agent object
    method:  str   # which method to call (default: "analyze")
    priority: int  # lower = dispatched first (unused for parallel gather, useful for logging)

    def __lt__(self, other: "AgentTask") -> bool:
        return self.priority < other.priority


# ── Dispatch table ────────────────────────────────────────────────────────────
# Maps (intent_label) → which agent keys should be included.
# An agent key appears in the result if ANY of its trigger intents is present.
# Order within a key's trigger list doesn't matter (set membership check).

_ROUTING_TABLE: list[dict[str, Any]] = [
    {
        "name":     "futures",
        "triggers": {"live_price", "risk", "forecast"},
        "method":   "analyze",
        "priority": 10,
    },
    {
        "name":     "risk",
        "triggers": {"risk", "alert"},
        "method":   "analyze",
        "priority": 20,
    },
    {
        "name":     "alert",
        "triggers": {"alert", "risk"},
        "method":   "analyze",
        "priority": 30,
    },
    {
        "name":     "forecast",
        "triggers": {"forecast", "risk"},
        "method":   "analyze",
        "priority": 40,
    },
    {
        "name":     "weather",
        "triggers": {"weather"},
        "method":   "analyze",
        "priority": 50,
    },
]


class IntentRouter:
    """
    Maps classified intent labels to a sorted list of AgentTasks.

    Args:
        agents: dict mapping agent name → agent object.
                Example: {"futures": FuturesAgent, "risk": RiskAgent, ...}

    Example:
        router = IntentRouter(agents={
            "futures": futures_agent,
            "risk":    risk_agent,
        })
        tasks = router.route(["live_price", "risk"])
        # → [AgentTask("futures", priority=10), AgentTask("risk", priority=20)]
    """

    def __init__(self, agents: dict[str, Any]) -> None:
        self._agents = agents

    def route(self, intents: list[str]) -> list[AgentTask]:
        """
        Given a list of intent labels, return a sorted list of AgentTasks
        for all agents whose trigger intents overlap with the given intents.

        Args:
            intents: List of classified intent labels from IntentClassifier.

        Returns:
            Sorted list of AgentTask descriptors (by priority, ascending).
            Empty list when no agents match or no agents are wired.
        """
        intent_set = set(intents)
        tasks: list[AgentTask] = []

        for rule in _ROUTING_TABLE:
            agent_name = rule["name"]
            # Only include if an agent with this name is actually wired
            agent_obj = self._agents.get(agent_name)
            if agent_obj is None:
                continue
            # Include if ANY trigger intent is present
            if intent_set & rule["triggers"]:
                tasks.append(AgentTask(
                    name=agent_name,
                    agent=agent_obj,
                    method=rule["method"],
                    priority=rule["priority"],
                ))

        return sorted(tasks)

    def describe(self) -> dict[str, list[str]]:
        """
        Return a human-readable description of the routing table.
        Useful for /api/v1/admin/routing-table debugging endpoint.
        """
        return {
            rule["name"]: sorted(rule["triggers"])
            for rule in _ROUTING_TABLE
            if rule["name"] in self._agents
        }
