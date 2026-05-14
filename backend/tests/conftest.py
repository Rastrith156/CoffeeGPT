"""
tests/conftest.py
=================
Task 4 — Shared pytest fixtures for all integration and contract tests.

Fixtures:
  mock_redis      → fakeredis.aioredis in-memory (no real Redis needed)
  mock_qdrant     → qdrant_client.QdrantClient(":memory:")
  mock_lmstudio   → AsyncMock provider returning canned responses
  async_client    → httpx.AsyncClient wrapping the FastAPI app
  seed_qdrant     → inserts 3 known coffee documents for RAG tests
"""
from __future__ import annotations

import asyncio
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

# Fake Redis — in-memory, no server needed
try:
    import fakeredis.aioredis as fake_aioredis
    _FAKEREDIS_AVAILABLE = True
except ImportError:
    _FAKEREDIS_AVAILABLE = False


# ── Event loop ────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def event_loop():
    """Single event loop for the entire test session."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ── Redis ─────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def mock_redis():
    """In-memory async Redis client (fakeredis)."""
    if not _FAKEREDIS_AVAILABLE:
        pytest.skip("fakeredis not installed")
    server = fake_aioredis.FakeServer()
    client = fake_aioredis.FakeRedis(server=server, decode_responses=True)
    yield client
    await client.aclose()


# ── Qdrant ────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_qdrant():
    """In-memory Qdrant client (no server needed)."""
    client = QdrantClient(":memory:")
    # Create the test collection
    client.create_collection(
        collection_name="coffee_intelligence",
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )
    return client


@pytest.fixture
def seed_qdrant(mock_qdrant: QdrantClient):
    """
    Insert 3 known coffee documents with deterministic vectors.
    Used by RAG pipeline tests to assert ranked retrieval order.
    """
    from qdrant_client.models import PointStruct
    import numpy as np

    docs = [
        {
            "id": 1,
            "text": "Arabica futures rose 3.2% following a severe frost warning in Brazil's Minas Gerais region.",
            "source_url": "https://example.com/arabica-frost",
            "title": "Arabica Frost Warning",
            "published_at": "2026-05-10T08:00:00Z",
        },
        {
            "id": 2,
            "text": "Robusta prices fell 1.5% as Vietnam reported a record harvest in Dak Lak province.",
            "source_url": "https://example.com/robusta-harvest",
            "title": "Vietnam Robusta Record",
            "published_at": "2026-05-11T10:00:00Z",
        },
        {
            "id": 3,
            "text": "ICO composite indicator retreated amid global demand softness and currency headwinds.",
            "source_url": "https://example.com/ico-composite",
            "title": "ICO Composite Decline",
            "published_at": "2026-05-12T12:00:00Z",
        },
    ]

    # Use deterministic seed for reproducible vectors
    rng = np.random.default_rng(seed=42)
    points = []
    for doc in docs:
        vec = rng.random(384).astype(np.float32)
        vec /= np.linalg.norm(vec)  # L2 normalise
        points.append(
            PointStruct(
                id=doc["id"],
                vector=vec.tolist(),
                payload={k: v for k, v in doc.items() if k != "id"},
            )
        )

    mock_qdrant.upsert(collection_name="coffee_intelligence", points=points)
    return mock_qdrant, docs


# ── LLM Mock ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_lmstudio():
    """
    AsyncMock provider that simulates LMStudio responses without a real server.
    - generate()        → returns a canned analysis string
    - generate_json()   → returns a canned dict
    - stream_generate() → yields 5 word tokens
    """

    async def _fake_stream(*args, **kwargs):
        for token in ["Coffee ", "market ", "analysis: ", "bullish ", "trend."]:
            yield token

    provider = MagicMock()
    provider.generate = AsyncMock(
        return_value="Coffee prices are trending upward due to supply constraints."
    )
    provider.generate_json = AsyncMock(
        return_value={
            "summary": "Bullish trend detected",
            "confidence": 0.87,
            "recommendation": "hold",
        }
    )
    provider.stream_generate = MagicMock(side_effect=_fake_stream)
    return provider


# ── FastAPI test client ───────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """
    httpx.AsyncClient wrapping the FastAPI app directly (no server needed).
    Patches Redis and LMStudio so tests are fully isolated.
    """
    from main import app

    # Patch Redis in rate limiter to avoid external connection
    with patch("core.rate_limit._get_redis_client", return_value=None):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
            headers={"X-API-Key": "bypass_dev_key"},
        ) as client:
            yield client


# ── Market Monitor fixture ────────────────────────────────────────────────────

@pytest.fixture
def mock_market_monitor(mock_redis):
    """MarketMonitor with injected fake Redis cache."""
    from streaming.redis_cache import RedisMarketCache
    from streaming.market_monitor import MarketMonitor

    cache = MagicMock(spec=RedisMarketCache)
    cache.get_arabica = AsyncMock(return_value=None)
    cache.get_robusta = AsyncMock(return_value=None)
    cache.push_alert = AsyncMock(return_value=True)
    cache.push_spike = AsyncMock(return_value=True)
    cache.update_arabica = AsyncMock(return_value=True)
    cache.update_robusta = AsyncMock(return_value=True)
    monitor = MarketMonitor(cache=cache)
    return monitor, cache
