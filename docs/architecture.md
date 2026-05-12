# CoffeeGPT Architecture

CoffeeGPT is structured as an enterprise-first intelligence platform, with the backend organized around reusable domain services instead of route-specific logic.

## Runtime layers

- `frontend/`
  Placeholder for the future Next.js dashboard. No UI work is started yet.
- `backend/api/`
  Thin FastAPI routers that expose typed endpoints and delegate to shared services.
- `backend/core/`
  Runtime configuration, logging, dependency container, database bootstrap, and Celery app.
- `backend/services/`
  Business capabilities for market, weather, news, health, forecasting, and orchestration.
- `backend/agents/`
  CoffeeGPT chatbot agent with RAG-aware answer generation.
- `backend/rag/`
  Chunking, retrieval, and vector indexing pipeline for Qdrant-backed knowledge retrieval.
- `backend/forecasting/`
  Forecast engine scaffold with readiness detection for Prophet and XGBoost.
- `backend/ingestion/`
  Connector registry, ingestion pipeline, and Celery task entrypoint.

## Data flow

1. Connectors collect raw market, weather, news, policy, buyer, export, and local-market signals.
2. The ingestion pipeline stores raw snapshots under `data/raw/`.
3. Processed summaries are written to `data/processed/`.
4. RAG chunking converts those records into vectorizable documents.
5. Qdrant stores embeddings for retrieval.
6. The chatbot agent retrieves context and asks the LM Studio local server to answer with grounding.
7. Forecasting and intelligence endpoints provide structured analytics on top of the same service layer.

## Phase 0 status

- Implemented:
  FastAPI runtime, typed API surface, health probes, orchestrator, RAG scaffold, ingestion registry, Celery entrypoint, Docker/dev scripts, and enterprise folder structure.
- Demo or scaffold mode:
  Market, forecast, buyer, and local-market data remain synthetic baselines until live providers are wired in.
- External dependencies required for full readiness:
  PostgreSQL, Redis, Qdrant, LM Studio, and optional API keys for live weather/news.
