from __future__ import annotations

import asyncio
from dataclasses import dataclass

from agents.chatbot_agent import CoffeeChatbotAgent
from core.config import settings
from core.database import init_db
from core.logger import logger
from ingestion.news_ingestor import NewsIngestor
from forecasting.engine import CoffeeForecastEngine
from ingestion.pipeline import IngestionPipeline
from rag.pipeline import RAGPipeline
from services.forecast_service import ForecastService
from services.health_service import HealthService
from services.lmstudio_client import LMStudioClient
from services.market_service import MarketService
from services.news_service import NewsService
from services.orchestrator import CoffeeIntelligenceOrchestrator
from services.weather_service import WeatherService


@dataclass
class ApplicationContainer:
    lmstudio_client: LMStudioClient
    health_service: HealthService
    market_service: MarketService
    weather_service: WeatherService
    news_service: NewsService
    forecast_service: ForecastService
    rag_pipeline: RAGPipeline
    chatbot_agent: CoffeeChatbotAgent
    ingestion_pipeline: IngestionPipeline
    news_ingestor: NewsIngestor
    orchestrator: CoffeeIntelligenceOrchestrator
    news_ingestion_task: asyncio.Task | None = None

    async def startup(self) -> None:
        settings.ensure_directories()
        try:
            init_db()
        except Exception as exc:
            logger.warning("Database initialization skipped during startup: {}", exc)
        await asyncio.to_thread(self.rag_pipeline.retriever.available)
        await self.news_ingestor.seed_bootstrap_article()
        if self.news_ingestion_task is None or self.news_ingestion_task.done():
            self.news_ingestion_task = asyncio.create_task(self.news_ingestor.run_forever())
        health_report = await self.health_service.collect_health()
        dependency_map = {item.name: item.status for item in health_report.services}
        logger.info("Dependency readiness: {}", dependency_map)

    async def shutdown(self) -> None:
        if self.news_ingestion_task is not None:
            self.news_ingestion_task.cancel()
            try:
                await self.news_ingestion_task
            except asyncio.CancelledError:
                pass
        await self.lmstudio_client.aclose()
        logger.info("CoffeeGPT runtime shutdown complete")


def build_container() -> ApplicationContainer:
    settings.ensure_directories()

    market_service = MarketService()
    weather_service = WeatherService()
    news_service = NewsService()
    forecast_engine = CoffeeForecastEngine()
    lmstudio_client = LMStudioClient()
    forecast_service = ForecastService(
        engine=forecast_engine,
        market_service=market_service,
        weather_service=weather_service,
    )
    health_service = HealthService(lmstudio_client=lmstudio_client)
    rag_pipeline = RAGPipeline()
    chatbot_agent = CoffeeChatbotAgent(
        retriever=rag_pipeline.retriever,
        lmstudio_client=lmstudio_client,
    )
    ingestion_pipeline = IngestionPipeline(
        market_service=market_service,
        weather_service=weather_service,
        news_service=news_service,
        rag_pipeline=rag_pipeline,
    )
    news_ingestor = NewsIngestor(ingestion_pipeline=ingestion_pipeline)
    orchestrator = CoffeeIntelligenceOrchestrator(
        chatbot_agent=chatbot_agent,
        market_service=market_service,
        weather_service=weather_service,
        news_service=news_service,
        forecast_service=forecast_service,
        ingestion_pipeline=ingestion_pipeline,
        health_service=health_service,
    )
    return ApplicationContainer(
        lmstudio_client=lmstudio_client,
        health_service=health_service,
        market_service=market_service,
        weather_service=weather_service,
        news_service=news_service,
        forecast_service=forecast_service,
        rag_pipeline=rag_pipeline,
        chatbot_agent=chatbot_agent,
        ingestion_pipeline=ingestion_pipeline,
        news_ingestor=news_ingestor,
        orchestrator=orchestrator,
    )
