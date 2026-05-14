"""
core/runtime.py
===============
Application container — wires all services, agents, streaming layer,
monitoring loop, and session memory into a single dependency graph.

HOT LAYER:
  RedisMarketCache  → FuturesStreamService  → MarketMonitor → IntelligenceLoop

COLD LAYER:
  Qdrant / PostgreSQL / historical ingestors

REASONING:
  OrchestratorAgent → specialized agents → CoffeeChatbotAgent (RAG)
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from agents.chatbot_agent import CoffeeChatbotAgent
from core.config import settings
from core.database import init_db
from core.logger import logger
from ingestion.futures_ingestor import FuturesIngestor
from ingestion.news_ingestor import NewsIngestor
from ingestion.weather_ingestor import WeatherIngestor
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

# ── HOT LAYER imports (graceful fallback when Redis is unavailable) ──────────
try:
    from streaming.redis_cache import RedisMarketCache
    from streaming.futures_stream import FuturesStreamService
    from streaming.market_monitor import MarketMonitor
    from monitoring.intelligence_loop import IntelligenceLoop
    from agents.futures_agent import FuturesAgent
    from agents.risk_agent import RiskAgent
    from agents.alert_agent import AlertAgent
    from agents.forecast_agent import ForecastAgent
    from agents.orchestrator_agent import OrchestratorAgent
    from agents.weather_agent import WeatherAgent
    from memory.session_memory import SessionMemory
    _STREAMING_AVAILABLE = True
except ImportError as _imp_err:
    logger.warning("Streaming layer import skipped: {}", _imp_err)
    _STREAMING_AVAILABLE = False


@dataclass
class ApplicationContainer:
    # ── Core services ────────────────────────────────────────────────────────
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
    weather_ingestor: WeatherIngestor
    futures_ingestor: FuturesIngestor
    orchestrator: CoffeeIntelligenceOrchestrator

    # ── HOT LAYER ────────────────────────────────────────────────────────────
    redis_cache: object = None
    futures_stream: object = None
    market_monitor: object = None
    intelligence_loop: object = None
    session_memory: object = None
    orchestrator_agent: object = None  # new multi-agent orchestrator

    # ── Background tasks ─────────────────────────────────────────────────────
    news_ingestion_task: asyncio.Task | None = None
    weather_ingestion_task: asyncio.Task | None = None
    futures_ingestion_task: asyncio.Task | None = None
    futures_stream_task: asyncio.Task | None = None
    market_monitor_task: asyncio.Task | None = None
    intelligence_loop_task: asyncio.Task | None = None

    async def startup(self) -> None:
        settings.ensure_directories()
        try:
            init_db()
        except Exception as exc:
            logger.warning("Database initialization skipped during startup: {}", exc)

        await asyncio.to_thread(self.rag_pipeline.retriever.available)
        await self.news_ingestor.seed_bootstrap_article()

        # ── Task 1: Intent Classifier Warm-up ────────────────────────────────
        from agents.intent_classifier import IntentClassifier
        redis_client = None
        if self.redis_cache and hasattr(self.redis_cache, "_get_client"):
            redis_client = await self.redis_cache._get_client()
        await IntentClassifier.instance().warm_up(redis_client=redis_client)

        # ── Cold-layer background ingestion ──────────────────────────────────
        if settings.run_background_tasks:
            if self.news_ingestion_task is None or self.news_ingestion_task.done():
                self.news_ingestion_task = asyncio.create_task(self.news_ingestor.run_forever())
            if self.weather_ingestion_task is None or self.weather_ingestion_task.done():
                self.weather_ingestion_task = asyncio.create_task(self.weather_ingestor.run_forever())
            if self.futures_ingestion_task is None or self.futures_ingestion_task.done():
                self.futures_ingestion_task = asyncio.create_task(self.futures_ingestor.run_forever())

        # ── HOT LAYER streaming tasks ─────────────────────────────────────────
        if _STREAMING_AVAILABLE and settings.run_background_tasks:
            if self.futures_stream is not None and (
                self.futures_stream_task is None or self.futures_stream_task.done()
            ):
                self.futures_stream_task = asyncio.create_task(self.futures_stream.start())
                logger.info("FuturesStreamService task started")

            if self.market_monitor is not None and (
                self.market_monitor_task is None or self.market_monitor_task.done()
            ):
                self.market_monitor_task = asyncio.create_task(self.market_monitor.start())
                logger.info("MarketMonitor task started")

            if self.intelligence_loop is not None and (
                self.intelligence_loop_task is None or self.intelligence_loop_task.done()
            ):
                self.intelligence_loop_task = asyncio.create_task(self.intelligence_loop.start())
                logger.info("IntelligenceLoop task started")

        health_report = await self.health_service.collect_health()
        dependency_map = {item.name: item.status for item in health_report.services}
        logger.info("Dependency readiness: {}", dependency_map)
        logger.info(
            "CoffeeGPT runtime started | streaming={} orchestrator={}",
            _STREAMING_AVAILABLE,
            self.orchestrator_agent is not None,
        )

    async def shutdown(self) -> None:
        # Cancel all background tasks
        for task_attr in (
            "news_ingestion_task",
            "weather_ingestion_task",
            "futures_ingestion_task",
            "futures_stream_task",
            "market_monitor_task",
            "intelligence_loop_task",
        ):
            task = getattr(self, task_attr, None)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Stop streaming services gracefully
        if _STREAMING_AVAILABLE:
            if self.futures_stream is not None:
                await self.futures_stream.stop()
            if self.market_monitor is not None:
                await self.market_monitor.stop()
            if self.intelligence_loop is not None:
                await self.intelligence_loop.stop()
            if self.redis_cache is not None:
                await self.redis_cache.aclose()
            if self.session_memory is not None:
                await self.session_memory.aclose()

        await self.lmstudio_client.aclose()
        logger.info("CoffeeGPT runtime shutdown complete")


def build_container() -> ApplicationContainer:
    settings.ensure_directories()

    # Fix #1: production safety guard — crash early with a clear message
    if settings.is_production:
        assert settings.secret_key not in ("change_me", "change_me_to_a_secure_random_string"), (
            "SECRET_KEY must be changed from the default value in production. "
            "Set SECRET_KEY=<random-string> in your .env file."
        )
        default_keys = {"coffeegpt_master_key_2026", "coffee_enterprise_key"}
        assert not any(k in default_keys for k in settings.api_keys), (
            "Default API keys detected in production. "
            "Replace API_KEYS with real secret keys in your .env file."
        )
        assert len(settings.api_keys) > 0, (
            "API_KEYS must not be empty in production. Set AUTH_ENABLED=true and provide real keys."
        )

    # ── Cold layer ────────────────────────────────────────────────────────────
    market_service   = MarketService()
    weather_service  = WeatherService()
    news_service     = NewsService()
    forecast_engine  = CoffeeForecastEngine()
    lmstudio_client  = LMStudioClient()
    forecast_service = ForecastService(
        engine=forecast_engine,
        market_service=market_service,
        weather_service=weather_service,
        news_service=news_service,
    )
    health_service   = HealthService(lmstudio_client=lmstudio_client)
    rag_pipeline     = RAGPipeline()

    # ── HOT LAYER ─────────────────────────────────────────────────────────────
    redis_cache      = None
    futures_stream   = None
    market_monitor   = None
    intel_loop       = None
    session_memory   = None
    futures_agent_obj = None
    risk_agent_obj   = None
    alert_agent_obj  = None
    forecast_agent_obj = None
    weather_agent_obj  = None
    orchestrator_agent_obj = None

    if _STREAMING_AVAILABLE:
        redis_cache    = RedisMarketCache()
        futures_stream = FuturesStreamService(cache=redis_cache)
        market_monitor = MarketMonitor(cache=redis_cache)
        intel_loop     = IntelligenceLoop(
            cache=redis_cache,
            market_service=market_service,
            weather_service=weather_service,
        )
        session_memory = SessionMemory()

        futures_agent_obj  = FuturesAgent(cache=redis_cache, market_service=market_service)
        risk_agent_obj     = RiskAgent(cache=redis_cache)
        alert_agent_obj    = AlertAgent(cache=redis_cache)
        forecast_agent_obj = ForecastAgent(cache=redis_cache, forecast_service=forecast_service)
        weather_agent_obj  = WeatherAgent(cache=redis_cache, weather_service=weather_service)

    # Fix #9: pass session_memory to chatbot_agent so Redis-backed history is used
    # ── Chatbot (gets redis_cache for live prefix) ────────────────────────────
    chatbot_agent = CoffeeChatbotAgent(
        retriever=rag_pipeline.retriever,
        lmstudio_client=lmstudio_client,
        redis_cache=redis_cache,
        session_memory=session_memory,
    )

    # Fix #10: wire WeatherAgent and pass all agents including weather to OrchestratorAgent
    # ── Multi-agent orchestrator ──────────────────────────────────────────────
    if _STREAMING_AVAILABLE:
        orchestrator_agent_obj = OrchestratorAgent(
            cache=redis_cache,
            futures_agent=futures_agent_obj,
            risk_agent=risk_agent_obj,
            alert_agent=alert_agent_obj,
            forecast_agent=forecast_agent_obj,
            chatbot_agent=chatbot_agent,
            weather_agent=weather_agent_obj,
        )

    ingestion_pipeline = IngestionPipeline(
        market_service=market_service,
        weather_service=weather_service,
        news_service=news_service,
        rag_pipeline=rag_pipeline,
    )
    news_ingestor    = NewsIngestor(ingestion_pipeline=ingestion_pipeline)
    weather_ingestor = WeatherIngestor(ingestion_pipeline=ingestion_pipeline)
    futures_ingestor = FuturesIngestor(ingestion_pipeline=ingestion_pipeline)

    orchestrator = CoffeeIntelligenceOrchestrator(
        chatbot_agent=chatbot_agent,
        market_service=market_service,
        weather_service=weather_service,
        news_service=news_service,
        forecast_service=forecast_service,
        ingestion_pipeline=ingestion_pipeline,
        health_service=health_service,
        orchestrator_agent=orchestrator_agent_obj,   # Fix #10
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
        weather_ingestor=weather_ingestor,
        futures_ingestor=futures_ingestor,
        orchestrator=orchestrator,
        # HOT LAYER
        redis_cache=redis_cache,
        futures_stream=futures_stream,
        market_monitor=market_monitor,
        intelligence_loop=intel_loop,
        session_memory=session_memory,
        orchestrator_agent=orchestrator_agent_obj,
    )
