"""
tests/conftest.py
=================
Shared pytest fixtures for all integration and contract tests.

Fixtures:
  mock_redis      → fakeredis.aioredis in-memory (no real Redis needed)
  mock_qdrant     → qdrant_client.QdrantClient(":memory:")
  mock_lmstudio   → AsyncMock provider returning canned responses
  async_client    → httpx.AsyncClient wrapping the FastAPI app
  seed_qdrant     → inserts 3 known coffee documents for RAG tests
  mock_market_monitor → MarketMonitor with injected mock RedisMarketCache

Fixes applied:
  - event_loop fixture removed (deprecated in pytest-asyncio ≥ 0.23) —
    asyncio_mode="auto" in pytest.ini/pyproject controls session-wide loop
  - async_client patches _get_redis_client with AsyncMock (not a sync mock)
    to prevent coroutine-not-awaited warnings in rate_limit middleware
  - fakeredis.FakeServer instantiation guarded for compat with both
    fakeredis 2.x API variants
"""
from __future__ import annotations

# ── Stub heavy security deps that may not be locally installed ────────────────
# python-jose and passlib are in requirements.txt but not always pip-installed
# in local dev venvs. We stub them at sys.modules level BEFORE any app module
# is imported so that core.security (which imports them at module scope) can
# be loaded in integration tests without the packages being present.
import sys as _sys
from unittest.mock import MagicMock as _MM

for _mod in (
    "jose", "jose.jwt", "jose.exceptions",
    "passlib", "passlib.context", "passlib.handlers",
    "passlib.handlers.bcrypt",
    "asyncpg", "asyncpg.pool", "asyncpg.connection",
    "databases",
):
    _sys.modules.setdefault(_mod, _MM())
# ─────────────────────────────────────────────────────────────────────────────
# These imports MUST come after the sys.modules stub block above.
# noqa: E402 suppresses "module level import not at top of file" — intentional.
from typing import AsyncGenerator  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402
from qdrant_client.models import Distance, VectorParams  # noqa: E402

# Fake Redis — in-memory, no server needed
try:
    import fakeredis.aioredis as fake_aioredis
    _FAKEREDIS_AVAILABLE = True
except ImportError:
    _FAKEREDIS_AVAILABLE = False


# ── Redis ─────────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def mock_redis():
    """In-memory async Redis client (fakeredis)."""
    if not _FAKEREDIS_AVAILABLE:
        pytest.skip("fakeredis not installed")
    try:
        # fakeredis 2.x
        server = fake_aioredis.FakeServer()
        client = fake_aioredis.FakeRedis(server=server, decode_responses=True)
    except AttributeError:
        # Older API — FakeServer may not exist
        client = fake_aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


# ── Qdrant ────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_qdrant():
    """In-memory Qdrant client (no server needed)."""
    client = QdrantClient(":memory:")
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

    rng = np.random.default_rng(seed=42)
    points = []
    for doc in docs:
        vec = rng.random(384).astype(np.float32)
        vec /= np.linalg.norm(vec)  # L2 normalise
        points.append(
            PointStruct(
                id=int(doc["id"]),
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
    Patches Redis (with AsyncMock) and LMStudio so tests are fully isolated.

    Fix: auth_enabled is patched to False so that tests don't need a real JWT.
    Fix: _get_redis_client must be an AsyncMock so rate-limit middleware works.
    """
    from main import app

    # Disable auth globally for integration tests
    with patch("core.config.settings.auth_enabled", False), patch(
        "core.rate_limit._get_redis_client",
        new_callable=AsyncMock,
        return_value=None,
    ):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            yield client


# ── Market Monitor fixture ────────────────────────────────────────────────────

@pytest.fixture
def mock_market_monitor():
    """MarketMonitor with injected fake RedisMarketCache."""
    from streaming.redis_cache import RedisMarketCache
    from streaming.market_monitor import MarketMonitor

    cache = MagicMock(spec=RedisMarketCache)
    cache.get_arabica      = AsyncMock(return_value=None)
    cache.get_robusta      = AsyncMock(return_value=None)
    cache.get_live_snapshot = AsyncMock(return_value={
        "arabica": None, "robusta": None,
        "volatility": {}, "recent_alerts": [],
    })
    cache.push_alert       = AsyncMock(return_value=True)
    cache.push_spike       = AsyncMock(return_value=True)
    cache.update_arabica   = AsyncMock(return_value=True)
    cache.update_robusta   = AsyncMock(return_value=True)
    cache.set_json         = AsyncMock(return_value=True)
    monitor = MarketMonitor(cache=cache)
    return monitor, cache
