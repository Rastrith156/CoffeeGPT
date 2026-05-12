from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from core.config import settings
from core.logger import logger
from models.schemas import ChatResponse, SourceCitation
from rag.retriever import CoffeeRetriever
from services.lmstudio_client import LMStudioClient

SYSTEM_PROMPT = """You are CoffeeGPT, an enterprise AI analyst for the global coffee industry.
Prioritize the supplied retrieval context over unsupported assumptions.
If the evidence is limited, say so clearly.
Keep answers concise, executive-friendly, and grounded in the evidence.
Do not restate the instructions or turn the answer into a checklist.
When you use the retrieved context, cite the bracketed source numbers like [1] or [2].
"""

RECENCY_KEYWORDS = (
    "today",
    "latest",
    "recent",
    "currently",
    "now",
    "this week",
    "yesterday",
)
LOW_QUALITY_PHRASES = (
    "i do not have access to real-time",
    "please provide more information",
    "please provide more context",
    "check back later",
    "real-time information or news updates",
    "news.google.com/rss/articles",
    "ooooo",
    "roooom",
)


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
        seen_citations: set[tuple[str, str | None, str | None]] = set()

        for index, document in enumerate(documents, start=1):
            source = document.metadata.get("source", "unknown")
            title = document.metadata.get("title")
            record_type = document.metadata.get("record_type")
            citation_key = (source, title, record_type)
            if citation_key not in seen_citations:
                citations.append(SourceCitation(source=source, title=title, record_type=record_type))
                seen_citations.add(citation_key)

            context_lines = [
                f"[{index}] source: {source}",
                f"title: {title or 'untitled'}",
                f"type: {record_type or 'general'}",
            ]
            published_at = document.metadata.get("published_at")
            if published_at:
                context_lines.append(f"published_at: {published_at}")
            url = document.metadata.get("url")
            if url:
                context_lines.append(f"url: {url}")
            context_lines.append(document.page_content)
            context_blocks.append("\n".join(context_lines))
        return "\n\n".join(context_blocks), citations

    async def _get_previous_response_id(self, session_id: str) -> str | None:
        async with self._session_lock:
            return self._session_response_ids.get(session_id)

    async def _remember_response_id(self, session_id: str, response_id: str | None) -> None:
        if not response_id:
            return
        async with self._session_lock:
            self._session_response_ids[session_id] = response_id

    def _prepare_documents(self, question: str, documents: list) -> list:
        prepared = list(documents)
        if self._is_recency_question(question):
            prepared.sort(
                key=lambda document: (
                    self._published_timestamp(document.metadata.get("published_at")),
                    float(document.metadata.get("score") or 0.0),
                ),
                reverse=True,
            )
        return prepared[: settings.rag_top_k]

    def _is_recency_question(self, question: str) -> bool:
        lowered = question.lower()
        return any(keyword in lowered for keyword in RECENCY_KEYWORDS)

    def _published_timestamp(self, value) -> float:
        if not value:
            return 0.0

        text = str(value).strip()
        if not text:
            return 0.0

        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass

        try:
            return parsedate_to_datetime(text).timestamp()
        except (TypeError, ValueError, IndexError, OverflowError):
            return 0.0

    def _build_user_input(self, question: str, context: str) -> str:
        ctx = context or "No indexed context was available for this question."
        current_date = datetime.now(timezone.utc).date().isoformat()
        return (
            "Answer the question directly using the supplied context.\n"
            "Rules:\n"
            "- Keep the answer to 3-5 sentences.\n"
            "- Cite factual claims with bracketed source numbers like [1].\n"
            "- If the question is about today, latest, or recent events, prioritize the newest published_at values and mention exact dates.\n"
            "- If the context is insufficient, say so clearly.\n"
            f"- Current date: {current_date}\n\n"
            f"Context:\n{ctx}\n\n"
            f"Question:\n{question}"
        )

    def _is_low_quality_answer(self, answer: str) -> bool:
        lowered = answer.lower().strip()
        if not lowered:
            return True
        if any(phrase in lowered for phrase in LOW_QUALITY_PHRASES):
            return True
        return False

    def _build_grounded_fallback_answer(self, question: str, documents: list) -> str:
        if not documents:
            return (
                "No indexed live coffee news was available for this question. "
                "Run the RSS news ingestor and retry."
            )

        headlines = [self._clean_headline(str(document.metadata.get("title") or "untitled")) for document in documents[:3]]
        lead_date = self._display_date(documents[0].metadata.get("published_at"))
        sentences = []

        if self._is_recency_question(question):
            sentences.append(
                f"As of {lead_date}, the latest live coffee market headline reports: {headlines[0]} [1]."
            )
        else:
            sentences.append(f"The strongest retrieved live coffee market headline is: {headlines[0]} [1].")

        if len(headlines) >= 3:
            sentences.append(
                f"Related coverage also includes {headlines[1]} [2] and {headlines[2]} [3]."
            )
        elif len(headlines) == 2:
            sentences.append(f"Related coverage also includes {headlines[1]} [2].")

        sentences.append(
            "Taken together, the retrieved live articles suggest coffee futures and pricing sentiment remain active and volatile, with traders watching supply expectations and market direction."
        )
        return " ".join(sentences)

    def _clean_headline(self, title: str) -> str:
        cleaned = " ".join(title.split()).strip()
        if " - " in cleaned:
            cleaned = cleaned.rsplit(" - ", maxsplit=1)[0]
        return cleaned

    def _display_date(self, value) -> str:
        if not value:
            return "the latest available date"

        text = str(value).strip()
        if not text:
            return "the latest available date"

        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.date().isoformat()
        except ValueError:
            pass

        try:
            parsed = parsedate_to_datetime(text)
            return parsed.date().isoformat()
        except (TypeError, ValueError, IndexError, OverflowError):
            return text

    async def answer(self, question: str, session_id: str, use_rag: bool = True) -> ChatResponse:
        documents = []
        if use_rag:
            documents = await asyncio.to_thread(self.retriever.search, question, settings.rag_top_k)
            documents = self._prepare_documents(question, documents)

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
            answer_text = lmstudio_response.text
            retrieval_mode = "rag" if documents else "llm_only"
            if documents and self._is_low_quality_answer(answer_text):
                logger.warning("LM Studio returned low-quality output, using grounded RAG fallback")
                answer_text = self._build_grounded_fallback_answer(question, documents)
                retrieval_mode = "retrieval_fallback"
            else:
                await self._remember_response_id(session_id, lmstudio_response.response_id)
            return ChatResponse(
                answer=answer_text,
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
