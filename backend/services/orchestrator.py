from __future__ import annotations

from typing import AsyncIterator

from core.config import settings
from core.logger import logger


class CoffeeIntelligenceOrchestrator:
    def __init__(
        self,
        chatbot_agent,
        market_service,
        weather_service,
        news_service,
        forecast_service,
        ingestion_pipeline,
        health_service,
        orchestrator_agent=None,   # Fix #10: wire multi-agent orchestrator
    ) -> None:
        self.chatbot_agent = chatbot_agent
        self.market_service = market_service
        self.weather_service = weather_service
        self.news_service = news_service
        self.forecast_service = forecast_service
        self.ingestion_pipeline = ingestion_pipeline
        self.health_service = health_service
        self.orchestrator_agent = orchestrator_agent  # Fix #10

    async def answer_chat(self, message: str, session_id: str, use_rag: bool = True):
        # Fix #10: delegate to OrchestratorAgent when available
        if self.orchestrator_agent is not None:
            return await self.orchestrator_agent.answer(
                question=message,
                session_id=session_id,
                use_rag=use_rag,
            )
        return await self.chatbot_agent.answer(
            question=message,
            session_id=session_id,
            use_rag=use_rag,
        )

    async def stream_chat(self, message: str, session_id: str) -> AsyncIterator[str]:
        """
        Fix #3: SSE streaming — calls LM Studio with stream=True and yields token chunks.
        Falls back to yielding the full answer as one chunk when streaming is unavailable.
        """
        client = self.chatbot_agent.lmstudio_client
        try:
            async for token in client.stream_chat(
                model=settings.llm_model,
                user_input=message,
                system_prompt=None,
            ):
                yield token
        except (AttributeError, NotImplementedError):
            # Graceful fallback: yield the full response as a single SSE chunk
            logger.debug("LMStudio streaming not available — falling back to single-chunk SSE")
            response = await self.answer_chat(message=message, session_id=session_id)
            answer_text = (
                response.get("answer") if isinstance(response, dict)
                else getattr(response, "answer", str(response))
            )
            yield answer_text or ""

    def platform_overview(self) -> dict:
        return {
            "status": "running",
            "platform": settings.app_name,
            "version": settings.app_version,
            "api_prefix": settings.api_prefix,
            "modules": [
                "chatbot_reasoning",
                "rag_retrieval",
                "market_intelligence",
                "weather_intelligence",
                "news_intelligence",
                "policy_tracking",
                "forecast_engine",
                "ingestion_pipeline",
            ],
            "service_modes": {
                "chatbot": f"lmstudio:{settings.llm_model}",
                "vector_store": settings.qdrant_collection,
                "forecast_engine": "enterprise_scaffold",
                "queue_mode": "celery" if settings.use_celery_for_ingestion else "background_tasks",
                "multi_agent": self.orchestrator_agent is not None,
            },
        }
