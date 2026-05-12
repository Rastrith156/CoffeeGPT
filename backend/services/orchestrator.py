from __future__ import annotations

from core.config import settings


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
    ) -> None:
        self.chatbot_agent = chatbot_agent
        self.market_service = market_service
        self.weather_service = weather_service
        self.news_service = news_service
        self.forecast_service = forecast_service
        self.ingestion_pipeline = ingestion_pipeline
        self.health_service = health_service

    async def answer_chat(self, message: str, session_id: str, use_rag: bool = True):
        return await self.chatbot_agent.answer(
            question=message,
            session_id=session_id,
            use_rag=use_rag,
        )

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
            },
        }
