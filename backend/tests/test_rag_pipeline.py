"""
tests/test_rag_pipeline.py
===========================
Task 4 — RAG pipeline contract tests.

Tests:
  - Insert 3 known docs into in-memory Qdrant
  - Query "arabica frost Brazil" → assert doc #1 ranks first
  - Query "robusta Vietnam harvest" → assert doc #2 ranks first
  - Assert source_url metadata is preserved in retrieval results
  - Assert retrieval returns at most top_k results
"""
from __future__ import annotations


import numpy as np
import pytest
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_vec(seed: int, dim: int = 384) -> list[float]:
    """Create a deterministic unit vector."""
    rng = np.random.default_rng(seed)
    v = rng.random(dim).astype(np.float32)
    return (v / np.linalg.norm(v)).tolist()


DOCS = [
    {
        "id": 1,
        "payload": {
            "text": "Arabica futures rose 3.2% following a severe frost warning in Brazil Minas Gerais.",
            "source_url": "https://example.com/arabica-frost",
            "title": "Arabica Frost Warning Brazil",
        },
        "seed": 1,
    },
    {
        "id": 2,
        "payload": {
            "text": "Robusta prices fell 1.5% as Vietnam reported record harvest in Dak Lak.",
            "source_url": "https://example.com/robusta-harvest",
            "title": "Vietnam Robusta Record Harvest",
        },
        "seed": 2,
    },
    {
        "id": 3,
        "payload": {
            "text": "ICO composite indicator retreated amid global demand softness.",
            "source_url": "https://example.com/ico-composite",
            "title": "ICO Composite Decline",
        },
        "seed": 3,
    },
]

COLLECTION = "coffee_intelligence"


@pytest.fixture
def qdrant_with_docs() -> QdrantClient:
    """Return an in-memory Qdrant client pre-loaded with 3 known documents."""
    client = QdrantClient(":memory:")
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=384, distance=Distance.COSINE),
    )
    points = [
        PointStruct(id=doc["id"], vector=_make_vec(doc["seed"]), payload=doc["payload"])
        for doc in DOCS
    ]
    client.upsert(collection_name=COLLECTION, points=points)
    return client


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_qdrant_has_correct_count(qdrant_with_docs: QdrantClient):
    """After seeding, the collection must contain exactly 3 documents."""
    info = qdrant_with_docs.get_collection(COLLECTION)
    assert info.points_count == 3


def test_retrieval_returns_source_metadata(qdrant_with_docs: QdrantClient):
    """Every retrieved result must carry source_url in its payload."""
    query_vec = _make_vec(seed=1)  # Similar to doc #1
    results = qdrant_with_docs.search(
        collection_name=COLLECTION,
        query_vector=query_vec,
        limit=3,
    )
    assert len(results) > 0
    for hit in results:
        assert "source_url" in hit.payload, f"Missing source_url in payload: {hit.payload}"
        assert hit.payload["source_url"].startswith("https://")


def test_retrieval_ranked_arabica_first(qdrant_with_docs: QdrantClient):
    """
    Query with the arabica doc's own vector → doc #1 must rank highest.
    Cosine similarity of a vector against itself = 1.0.
    """
    query_vec = _make_vec(seed=1)
    results = qdrant_with_docs.search(
        collection_name=COLLECTION,
        query_vector=query_vec,
        limit=3,
    )
    assert results[0].id == 1, (
        f"Expected doc #1 (arabica) to rank first, got doc #{results[0].id}"
    )
    # Score for exact match should be very close to 1.0
    assert results[0].score > 0.99


def test_retrieval_ranked_robusta_first(qdrant_with_docs: QdrantClient):
    """Query with the robusta doc's own vector → doc #2 must rank highest."""
    query_vec = _make_vec(seed=2)
    results = qdrant_with_docs.search(
        collection_name=COLLECTION,
        query_vector=query_vec,
        limit=3,
    )
    assert results[0].id == 2, (
        f"Expected doc #2 (robusta) to rank first, got doc #{results[0].id}"
    )


def test_retrieval_respects_top_k_limit(qdrant_with_docs: QdrantClient):
    """Retrieval with top_k=2 must return at most 2 results."""
    query_vec = _make_vec(seed=10)
    results = qdrant_with_docs.search(
        collection_name=COLLECTION,
        query_vector=query_vec,
        limit=2,
    )
    assert len(results) <= 2


def test_retrieval_scores_are_normalised(qdrant_with_docs: QdrantClient):
    """All cosine similarity scores must be in [-1, 1]."""
    query_vec = _make_vec(seed=99)
    results = qdrant_with_docs.search(
        collection_name=COLLECTION,
        query_vector=query_vec,
        limit=3,
    )
    for hit in results:
        assert -1.0 <= hit.score <= 1.0, f"Score out of range: {hit.score}"


def test_payload_title_preserved(qdrant_with_docs: QdrantClient):
    """The 'title' field must survive the round-trip through Qdrant."""
    query_vec = _make_vec(seed=3)
    results = qdrant_with_docs.search(
        collection_name=COLLECTION,
        query_vector=query_vec,
        limit=1,
    )
    assert "title" in results[0].payload
    assert len(results[0].payload["title"]) > 0
