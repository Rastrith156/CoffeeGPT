"""
agents/chatbot/response_synthesizer.py
=======================================
ISSUE #3 FIX — Extracted LLM response synthesis logic from chatbot_agent.py.

Responsibilities:
  - Call LMStudio LLM with prepared prompt
  - Post-process and clean the raw LLM output
  - Detect low-quality / hallucinated answers
  - Manage session memory (read prior context / persist new exchange)
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from core.config import settings
from core.errors import LLMError, GenerationError
from core.logger import logger, bind_context

# ── Patterns ──────────────────────────────────────────────────────────────────

SOURCE_SECTION_PATTERN = re.compile(
    r"(?:^|\n)(?:sources?|references?)\s*:.*$",
    re.IGNORECASE | re.DOTALL,
)
CITATION_PATTERN = re.compile(r"\[(\d+)\]")

LOW_QUALITY_PHRASES: tuple[str, ...] = (
    "i do not have access to real-time",
    "i don't have access to real-time",
    "real-time information or news updates",
    "i cannot browse",
    "i can't browse",
    "as an ai",
    "please provide more information",
    "please provide more context",
    "check back later",
    "news.google.com/rss/articles",
    "ooooo",
    "roooom",
)

SYSTEM_PROMPT = (
    "You are CoffeeGPT, a coffee market intelligence analyst.\n"
    "Use only the retrieved context supplied by the application.\n"
    "Do not rely on outside knowledge, browsing, or speculation.\n"
    "Write in a polished market-intelligence tone: direct, concise, and evidence-led.\n"
    "Never mention missing access, browsing limits, training data, or system limitations.\n"
    "Lead with the conclusion, then explain the main drivers and near-term implication.\n"
    "When multiple signal types are present, synthesize futures, weather, news, and historical context"
    " into one coherent market view.\n"
    "Explain whether the signals reinforce each other or conflict.\n"
    "Cite factual claims with bracketed source numbers like [1] that match the provided context blocks.\n"
    "Do not append a Sources or References section.\n"
    "If the retrieved context does not establish an answer, say exactly what is not established.\n"
)


class ResponseSynthesizer:
    """
    Orchestrates the LLM call and post-processing pipeline.

    Does NOT perform retrieval or context assembly — those are upstream.
    """

    def __init__(self, lmstudio_client=None) -> None:
        self._client = lmstudio_client
        self._log = bind_context(component="response_synthesizer")

    # ── Session memory helpers ────────────────────────────────────────────────

    async def get_prior_response_id(self, session_memory, session_id: str) -> str | None:
        """Read last_response_id from Redis-backed session memory."""
        if session_memory is None:
            return None
        try:
            session = await session_memory.load(session_id)
            return session.get("last_response_id")
        except Exception as exc:
            self._log.warning("Failed to read prior response_id (session={}): {}", session_id, exc)
            return None

    async def persist_response_id(
        self,
        session_memory,
        session_id: str,
        response_id: str | None,
    ) -> None:
        """Persist response_id into Redis session memory for multi-turn continuity."""
        if not response_id or session_memory is None:
            return
        try:
            session = await session_memory.load(session_id)
            session["last_response_id"] = response_id
            await session_memory.save(session_id, session)
        except Exception as exc:
            self._log.warning("Failed to persist response_id (session={}): {}", session_id, exc)

    async def get_prior_context(self, session_memory, session_id: str) -> str:
        """Build prior conversation context summary for multi-turn coherence."""
        if session_memory is None:
            return ""
        try:
            return await session_memory.build_context_summary(session_id)
        except Exception as exc:
            self._log.warning("Failed to build context summary (session={}): {}", session_id, exc)
            return ""

    async def persist_exchange(
        self,
        session_memory,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """Append Q&A exchange to session memory for future context."""
        if session_memory is None:
            return
        try:
            await session_memory.append_exchange(
                session_id=session_id,
                user_message=user_message,
                assistant_message=assistant_message,
            )
        except Exception as exc:
            self._log.warning("Failed to append exchange (session={}): {}", session_id, exc)

    # ── Core synthesis ────────────────────────────────────────────────────────

    async def synthesize(
        self,
        user_input: str,
        previous_response_id: str | None = None,
    ) -> tuple[str, str | None, str]:
        """
        Call the LLM and return (answer_text, response_id, model_name).

        Raises:
            LLMError: on connection failure or timeout.
            GenerationError: on empty/malformed LLM response.
        """
        if self._client is None:
            raise LLMError(
                "LMStudio client not configured",
                context={"hint": "pass lmstudio_client to CoffeeChatbotAgent"},
            )

        try:
            response = await self._client.chat(
                model=settings.llm_model,
                user_input=user_input,
                system_prompt=SYSTEM_PROMPT,
                previous_response_id=previous_response_id,
                store=True,
            )
        except asyncio.TimeoutError as exc:
            raise LLMError(
                "LLM request timed out",
                context={"model": settings.llm_model},
            ) from exc
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(
                f"LLM call failed: {exc}",
                context={"model": settings.llm_model},
            ) from exc

        raw_text = getattr(response, "text", "") or ""
        if not raw_text.strip():
            raise GenerationError(
                "LLM returned empty response",
                context={"model": settings.llm_model},
            )

        answer_text = self._post_process_answer(raw_text)
        response_id: str | None = getattr(response, "response_id", None)
        model_name: str = getattr(response, "model_instance_id", None) or settings.llm_model
        return answer_text, response_id, model_name

    # ── Quality detection ─────────────────────────────────────────────────────

    def is_low_quality(self, answer: str, citation_count: int) -> bool:
        """
        Return True if the answer is low-quality or hallucinated.

        Checks:
          - Empty answer
          - Contains known low-quality phrases (AI limitation disclaimers, etc.)
          - Has no citations when sources were provided
          - References out-of-range citation numbers
        """
        lowered = answer.lower().strip()
        if not lowered:
            return True
        if any(phrase in lowered for phrase in LOW_QUALITY_PHRASES):
            return True
        citations = [int(m) for m in CITATION_PATTERN.findall(answer)]
        if citation_count > 0 and not citations:
            return True
        if any(n < 1 or n > citation_count for n in citations):
            return True
        return False

    # ── Post-processing ───────────────────────────────────────────────────────

    def _post_process_answer(self, answer: str) -> str:
        """
        Clean raw LLM output:
          - Normalise line endings
          - Strip appended Sources/References sections
          - Collapse duplicate adjacent citation brackets [1] [1]
          - Collapse excessive blank lines
          - Strip trailing whitespace
        """
        cleaned = answer.replace("\r\n", "\n").replace("\r", "\n").strip()
        cleaned = SOURCE_SECTION_PATTERN.sub("", cleaned).strip()
        cleaned = re.sub(r"(\[\d+\])(?:\s+\1)+", r"\1", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        return cleaned.strip()

