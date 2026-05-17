"""
agents/chatbot_agent.py
========================
CoffeeGPT Chatbot Agent — Thin Orchestrator.

ISSUE #3 FIX: this file has been refactored from ~676 lines to ~130 lines.
All extracted logic now lives in agents/chatbot/:
  PromptBuilder       — context formatting, user-input assembly
  ResponseSynthesizer — LLM call, quality detection, post-processing
  CitationFormatter   — source-group finders
  FallbackHandler     — grounded fallback + no-context answers
  ContextAssembler    — Redis hot-layer live prefix

Public API:
  CoffeeChatbotAgent.answer(question, session_id, use_rag) -> ChatResponse
  (unchanged — backward compatible with orchestrator_agent.py)
"""
from __future__ import annotations

import asyncio
from typing import Any

from core.config import settings
from core.errors import LLMError, GenerationError, RedisError, RetrievalError
from core.logger import logger, bind_context
from models.schemas import ChatResponse, SourceCitation
from rag.retriever import CoffeeRetriever
from services.lmstudio_client import LMStudioClient

from agents.chatbot.prompt_builder import PromptBuilder
from agents.chatbot.response_synthesizer import ResponseSynthesizer
from agents.chatbot.citation_formatter import CitationFormatter
from agents.chatbot.fallback_handler import FallbackHandler
from agents.chatbot.context_assembler import ContextAssembler

# Optional Redis import — graceful fallback when unavailable
try:
    from streaming.redis_cache import RedisMarketCache as _RedisMarketCache
    _REDIS_AVAILABLE = True
except ImportError:
    _REDIS_AVAILABLE = False


class CoffeeChatbotAgent:
    """
    Coffee market intelligence chatbot agent.

    Orchestrates the full answer pipeline:
      1. Redis hot-layer context prefix (live prices)
      2. Vector-store RAG retrieval (Qdrant)
      3. Context formatting and prompt assembly
      4. LLM synthesis (LMStudio)
      5. Quality checking → grounded fallback if needed
      6. Session memory persistence
    """

    def __init__(
        self,
        retriever: CoffeeRetriever | None = None,
        lmstudio_client: LMStudioClient | None = None,
        redis_cache=None,
        session_memory=None,
    ) -> None:
        self.retriever       = retriever or CoffeeRetriever()
        self._session_memory = session_memory
        self._log            = bind_context(component="chatbot_agent")

        # Hot-layer cache (Redis) — optional, fails gracefully
        if redis_cache is not None:
            self._cache = redis_cache
        elif _REDIS_AVAILABLE:
            self._cache = _RedisMarketCache()
        else:
            self._cache = None

        # Decomposed sub-modules
        lm = lmstudio_client or LMStudioClient()
        self._prompt_builder   = PromptBuilder()
        self._synthesizer      = ResponseSynthesizer(lmstudio_client=lm)
        self._citation_fmt     = CitationFormatter()
        self._fallback_handler = FallbackHandler()
        self._context_assembler = ContextAssembler(cache=self._cache)

    # ── Public API ────────────────────────────────────────────────────────────

    async def answer(
        self,
        question: str,
        session_id: str,
        use_rag: bool = True,
    ) -> ChatResponse:
        """
        Main entry point — orchestrates all intelligence layers and returns
        a structured ChatResponse.

        Args:
            question:   User question string.
            session_id: Session identifier for multi-turn memory.
            use_rag:    Whether to invoke RAG retrieval.

        Returns:
            ChatResponse with answer, citations, and metadata.
        """
        # ── Step 1: Live Redis hot-layer context ─────────────────────────────
        live_prefix = await self._context_assembler.get_live_prefix(question)

        # ── Step 2: RAG retrieval ────────────────────────────────────────────
        documents: list = []
        if use_rag:
            retrieval_limit = max(
                settings.rag_top_k * settings.rag_retrieval_multiplier,
                settings.rag_top_k + 3,
            )
            try:
                documents = await asyncio.to_thread(
                    self.retriever.search, question, retrieval_limit
                )
            except Exception as exc:
                self._log.warning("RAG retrieval failed (degrading to live-only): {}", exc)
                documents = []

            if documents:
                documents = self._prompt_builder.prepare_documents(question, documents)

            if not documents and not live_prefix:
                return self._no_context_response(question, session_id)

        # ── Step 3: Context assembly ─────────────────────────────────────────
        context, citations, source_groups = self._prompt_builder.build_context(
            question, documents
        )
        if live_prefix:
            context = live_prefix + ("\n\n" + context if context else "")

        retrieval_mode = (
            "rag+live" if live_prefix and documents
            else "live_redis" if live_prefix
            else "rag"
        )

        # ── Step 4: Session memory — prior context ───────────────────────────
        prior_context      = await self._synthesizer.get_prior_context(
            self._session_memory, session_id
        )
        previous_resp_id   = await self._synthesizer.get_prior_response_id(
            self._session_memory, session_id
        )

        # ── Step 5: Prompt assembly ──────────────────────────────────────────
        user_input = self._prompt_builder.build_user_input(
            question, context, prior_context=prior_context
        )

        # ── Step 6: LLM synthesis ────────────────────────────────────────────
        try:
            answer_text, response_id, model_name = await self._synthesizer.synthesize(
                user_input=user_input,
                previous_response_id=previous_resp_id,
            )

            # Quality gate → grounded fallback
            if documents and self._synthesizer.is_low_quality(answer_text, len(citations)):
                self._log.warning(
                    "LLM output is low-quality — switching to grounded RAG fallback"
                )
                answer_text    = self._fallback_handler.build_grounded_fallback(
                    question, source_groups
                )
                retrieval_mode = "retrieval_fallback"
                response_id    = None
                model_name     = settings.llm_model
            else:
                await self._synthesizer.persist_response_id(
                    self._session_memory, session_id, response_id
                )

            # Persist exchange to session memory
            await self._synthesizer.persist_exchange(
                self._session_memory, session_id, question, answer_text
            )

            return ChatResponse(
                answer=answer_text,
                sources=citations,
                session_id=session_id,
                model=model_name,
                provider="lmstudio",
                response_id=response_id,
                retrieval_mode=retrieval_mode,
            )

        except (LLMError, GenerationError) as exc:
            self._log.warning("LLM synthesis failed → retrieval fallback: {}", exc)

        # ── Step 7: LLM hard failure — grounded fallback ─────────────────────
        if documents:
            return ChatResponse(
                answer=self._fallback_handler.build_grounded_fallback(
                    question, source_groups
                ),
                sources=citations,
                session_id=session_id,
                model=settings.llm_model,
                provider="lmstudio",
                retrieval_mode="retrieval_fallback",
            )

        return self._no_context_response(question, session_id)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _no_context_response(self, question: str, session_id: str) -> ChatResponse:
        return ChatResponse(
            answer=self._fallback_handler.build_no_context_answer(question),
            sources=[],
            session_id=session_id,
            model=settings.llm_model,
            provider="lmstudio",
            retrieval_mode="no_context",
        )
