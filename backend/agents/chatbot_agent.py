from __future__ import annotations

import asyncio

from loguru import logger

from core.config import settings
from models.schemas import ChatResponse, SourceCitation
from rag.retriever import CoffeeRetriever
from services.lmstudio_client import LMStudioClient

SYSTEM_PROMPT = """You are CoffeeGPT, an enterprise AI analyst for the global coffee industry.
Prioritize the supplied retrieval context over unsupported assumptions.
If the evidence is limited, say so clearly.
Keep answers concise, executive-friendly, and grounded in the evidence.
When you use the retrieved context, cite the bracketed source numbers like [1] or [2].
"""


class CoffeeChatbotAgent:
    def __init__(
        self,
        retriever: CoffeeRetriever | None = None,
        lmstudio_client: LMStudioClient | None = None,
    ) -> None:
        self.retriever = retriever or CoffeeRetriever()
        self.lmstudio_client = lmstudio_client or LMStudioClient()
        self._session_response_ids: dict[str, str] = {}
        self._session_lock = asyncio.Lock()

    def _build_context(self, documents: list) -> tuple[str, list[SourceCitation]]:
        context_blocks: list[str] = []
        citations: list[SourceCitation] = []

        for index, document in enumerate(documents, start=1):
            source = document.metadata.get("source", "unknown")
            title = document.metadata.get("title")
            record_type = document.metadata.get("record_type")
            citations.append(SourceCitation(source=source, title=title, record_type=record_type))
            context_blocks.append(
                "\n".join(
                    [
                        f"[{index}] source: {source}",
                        f"title: {title or 'untitled'}",
                        f"type: {record_type or 'general'}",
                        document.page_content,
                    ]
                )
            )
        return "\n\n".join(context_blocks), citations

    async def _get_previous_response_id(self, session_id: str) -> str | None:
        async with self._session_lock:
            return self._session_response_ids.get(session_id)

    async def _remember_response_id(self, session_id: str, response_id: str | None) -> None:
        if not response_id:
            return
        async with self._session_lock:
            self._session_response_ids[session_id] = response_id

    def _build_user_input(self, question: str, context: str) -> str:
        return "\n\n".join(
            [
                "Retrieved coffee intelligence context:",
                context or "No indexed context was available for this question.",
                "User question:",
                question,
            ]
        )

    async def answer(self, question: str, session_id: str, use_rag: bool = True) -> ChatResponse:
        documents = []
        if use_rag:
            documents = await asyncio.to_thread(self.retriever.search, question, settings.rag_top_k)

        context, citations = self._build_context(documents)
        previous_response_id = await self._get_previous_response_id(session_id)
        user_input = self._build_user_input(question, context)

        try:
            lmstudio_response = await self.lmstudio_client.chat(
                model=settings.llm_model,
                user_input=user_input,
                system_prompt=SYSTEM_PROMPT,
                previous_response_id=previous_response_id,
                store=True,
            )
            await self._remember_response_id(session_id, lmstudio_response.response_id)
            retrieval_mode = "rag" if documents else "llm_only"
            return ChatResponse(
                answer=lmstudio_response.text,
                sources=citations,
                session_id=session_id,
                model=lmstudio_response.model_instance_id or settings.llm_model,
                provider="lmstudio",
                response_id=lmstudio_response.response_id,
                retrieval_mode=retrieval_mode,
            )
        except Exception as exc:
            logger.warning("LLM response failed, using retrieval fallback: {}", exc)
            if documents:
                fallback_answer = (
                    "LM Studio is not currently reachable, so this response is a retrieval fallback. "
                    "Relevant indexed sources were found for your question."
                )
                return ChatResponse(
                    answer=fallback_answer,
                    sources=citations,
                    session_id=session_id,
                    model=settings.llm_model,
                    provider="lmstudio",
                    retrieval_mode="retrieval_fallback",
                )
            return ChatResponse(
                answer=(
                    "LM Studio is not currently reachable and no indexed context was available. "
                    "Start Qdrant and the LM Studio local server, then retry the question."
                ),
                sources=[],
                session_id=session_id,
                model=settings.llm_model,
                provider="lmstudio",
                retrieval_mode="unavailable",
            )
