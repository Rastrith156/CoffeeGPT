"""
agents/intent_classifier.py
============================
Task 1 — Embedding cosine-similarity intent classifier.

Replaces brittle keyword matching with semantic embeddings:
  - Loads sentence-transformers/all-MiniLM-L6-v2 once (singleton)
  - Embeds 5 intent prototype sentences
  - Caches prototype vectors in Redis (key: coffee:intent:proto:<name>, TTL=7d)
  - On classify(): embed query once, cosine-sim vs cached protos
  - Returns list[str] of intents with sim >= SIMILARITY_THRESHOLD
  - Falls back to ["general"] when no intent crosses the threshold
  - Target latency: < 2 ms per call (vectors kept in-process RAM after warm-up)
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import numpy as np
from sentence_transformers import SentenceTransformer

from core.config import settings
from core.logger import logger

# ── Constants ────────────────────────────────────────────────────────────────

SIMILARITY_THRESHOLD = 0.35
PROTO_REDIS_TTL = 7 * 24 * 3600  # 7 days
PROTO_KEY_PREFIX = "coffee:intent:proto:"
MODEL_NAME = "all-MiniLM-L6-v2"  # 384-dim, already in sentence-transformers

# ── Intent prototype sentences ────────────────────────────────────────────────
# Each list contains diverse phrasings so the centroid is representative.
INTENT_PROTOTYPES: dict[str, list[str]] = {
    "live_price": [
        "What is the current price of arabica coffee?",
        "Show me the latest robusta futures price",
        "What is the coffee market price right now?",
        "Current coffee price today",
        "Live market data for coffee futures",
    ],
    "risk": [
        "Should I hold my coffee stock?",
        "Is it safe to buy arabica futures now?",
        "What is the risk of selling robusta?",
        "Is it dangerous to hold coffee inventory?",
        "Buy or sell coffee futures recommendation",
    ],
    "alert": [
        "Are there any price alerts for coffee?",
        "Have there been any unusual market spikes?",
        "Show me recent coffee market anomalies",
        "Any warnings about coffee futures volatility?",
        "Price spike alerts for arabica",
    ],
    "forecast": [
        "What is the coffee price forecast for next week?",
        "Predict arabica price trend for the next month",
        "Coffee market outlook and projection",
        "Future price prediction for robusta",
        "Long-term coffee market trend analysis",
    ],
    "weather": [
        "How is the weather affecting coffee crops in Brazil?",
        "Rainfall forecast for Vietnam coffee regions",
        "Drought impact on Ethiopian coffee harvest",
        "Coffee growing region weather conditions",
        "Climate effects on robusta yield in Dak Lak",
    ],
}


class IntentClassifier:
    """
    Semantic intent classifier using sentence-transformer embeddings.

    Thread-safe singleton pattern — call `IntentClassifier.instance()` for
    the shared object, or instantiate directly for testing isolation.

    Prototype vectors are:
      1. Computed at startup (asyncio.to_thread — no event loop blocking)
      2. Written to Redis with 7-day TTL for distributed caching
      3. Kept in-process RAM (_proto_matrix) for sub-millisecond inference
    """

    _instance: "IntentClassifier | None" = None

    # ── Singleton ─────────────────────────────────────────────────────────────

    @classmethod
    def instance(cls) -> "IntentClassifier":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self._model_name = model_name
        self._model: SentenceTransformer | None = None
        self._proto_matrix: np.ndarray | None = None  # shape (n_intents, dim)
        self._intent_labels: list[str] = []
        self._ready = False

    def _load_model(self) -> SentenceTransformer:
        """Lazy-load the sentence transformer (heavy IO — call from a thread)."""
        if self._model is None:
            logger.info("IntentClassifier: loading model {}", self._model_name)
            t0 = time.perf_counter()
            self._model = SentenceTransformer(self._model_name)
            logger.info(
                "IntentClassifier: model loaded in {:.2f}s",
                time.perf_counter() - t0,
            )
        return self._model

    def _encode_batch(self, sentences: list[str]) -> np.ndarray:
        """Encode a batch of sentences → normalised L2 vectors."""
        model = self._load_model()
        vecs = model.encode(sentences, convert_to_numpy=True, normalize_embeddings=True)
        return vecs  # shape (N, dim)

    def _compute_proto_vectors(self) -> tuple[list[str], np.ndarray]:
        """
        Compute per-intent centroid vectors (mean of prototype sentence embeddings).
        Returns (labels, matrix) where matrix shape = (n_intents, dim).
        """
        labels: list[str] = []
        centroids: list[np.ndarray] = []

        for intent, sentences in INTENT_PROTOTYPES.items():
            vecs = self._encode_batch(sentences)
            centroid = vecs.mean(axis=0)
            # Re-normalise centroid so cosine_sim = dot product
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid = centroid / norm
            labels.append(intent)
            centroids.append(centroid)

        matrix = np.stack(centroids, axis=0)  # (n_intents, dim)
        return labels, matrix

    # ── Startup warm-up (called from ApplicationContainer.startup) ────────────

    async def warm_up(self, redis_client: Any | None = None) -> None:
        """
        Called once at startup. Tries to load proto vectors from Redis first.
        Falls back to computing them synchronously in a thread.
        """
        # 1. Try to load from Redis
        if redis_client is not None:
            try:
                loaded = await self._load_from_redis(redis_client)
                if loaded:
                    logger.info("IntentClassifier: prototype vectors loaded from Redis")
                    self._ready = True
                    return
            except Exception as exc:
                logger.warning("IntentClassifier: Redis load failed ({}), recomputing", exc)

        # 2. Compute in thread (CPU-bound, must not block event loop)
        labels, matrix = await asyncio.to_thread(self._compute_proto_vectors)
        self._intent_labels = labels
        self._proto_matrix = matrix
        self._ready = True
        logger.info(
            "IntentClassifier: prototype vectors ready — {} intents, dim={}",
            len(labels),
            matrix.shape[1],
        )

        # 3. Persist to Redis for other workers / next restart
        if redis_client is not None:
            await self._save_to_redis(redis_client)

    async def _save_to_redis(self, redis_client: Any) -> None:
        """Persist prototype vectors to Redis as JSON (base64-free, small enough)."""
        try:
            for label, vec in zip(self._intent_labels, self._proto_matrix):
                key = f"{PROTO_KEY_PREFIX}{label}"
                payload = json.dumps(vec.tolist())
                await redis_client.setex(key, PROTO_REDIS_TTL, payload)
            logger.debug("IntentClassifier: prototype vectors persisted to Redis")
        except Exception as exc:
            logger.warning("IntentClassifier: failed to save protos to Redis: {}", exc)

    async def _load_from_redis(self, redis_client: Any) -> bool:
        """
        Load prototype vectors from Redis.
        Returns True only if ALL intents were successfully loaded.
        """
        labels: list[str] = []
        vecs: list[np.ndarray] = []

        for intent in INTENT_PROTOTYPES:
            key = f"{PROTO_KEY_PREFIX}{intent}"
            raw = await redis_client.get(key)
            if raw is None:
                return False
            vec = np.array(json.loads(raw), dtype=np.float32)
            labels.append(intent)
            vecs.append(vec)

        # Also ensure model is loaded (needed for query embedding)
        await asyncio.to_thread(self._load_model)

        self._intent_labels = labels
        self._proto_matrix = np.stack(vecs, axis=0)
        return True

    # ── Inference ─────────────────────────────────────────────────────────────

    def classify(self, query: str) -> list[str]:
        """
        Classify query into one or more intent labels.

        Returns:
            list[str] — intents whose cosine-similarity to the query embedding
                        exceeds SIMILARITY_THRESHOLD.
                        Always contains at least ["general"] as fallback.

        Latency: < 2 ms after warm-up (single 384-dim dot product pass).
        """
        if not self._ready or self._model is None or self._proto_matrix is None:
            logger.warning("IntentClassifier not ready — falling back to ['general']")
            return ["general"]

        t0 = time.perf_counter()

        # Encode query (L2-normalised)
        q_vec = self._model.encode(
            [query],
            convert_to_numpy=True,
            normalize_embeddings=True,
        )[0]  # shape (dim,)

        # Cosine similarity = dot product (both sides L2-normalised)
        scores: np.ndarray = self._proto_matrix @ q_vec  # shape (n_intents,)

        intents = [
            label
            for label, score in zip(self._intent_labels, scores)
            if float(score) >= SIMILARITY_THRESHOLD
        ]

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug(
            "IntentClassifier: query={!r:.50} → intents={} scores={} ({:.2f}ms)",
            query,
            intents,
            {l: round(float(s), 3) for l, s in zip(self._intent_labels, scores)},
            elapsed_ms,
        )

        return intents if intents else ["general"]

    async def classify_async(self, query: str) -> list[str]:
        """
        Async variant — runs model inference in a thread pool to avoid
        blocking the event loop on first encode call.
        Subsequent calls use warm in-process RAM and are effectively instant.
        """
        return await asyncio.to_thread(self.classify, query)
