from __future__ import annotations

import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse

from langchain_core.documents import Document
from rag.embedder import EmbeddingService
from rag.store import CoffeeVectorStore

from core.config import settings
from core.logger import logger

RECENCY_KEYWORDS = (
    "today",
    "latest",
    "recent",
    "currently",
    "now",
    "this week",
    "yesterday",
)

SOURCE_RELIABILITY_HINTS = {
    "news_board": 0.98,
    "news_reuters": 0.96,
    "news_scraper": 0.92,
    "news_api": 0.88,
    "news_rss": 0.82,
    "futures": 0.95,
    "prices": 0.90,
    "weather": 0.90,
    "policies": 0.91,
    "exports": 0.89,
    "buyers": 0.86,
    "local_markets": 0.84,
    "forecasting": 0.93,
    "bootstrap_news": 0.78,
}

DOMAIN_RELIABILITY_HINTS = {
    "reuters.com": 0.97,
    "coffeeboard.gov.in": 0.98,
    "globalcoffeeplatform.org": 0.94,
    "newsapi.org": 0.86,
    "example.com": 0.72,
}

LOW_SIGNAL_TERMS = (
    "market size",
    "industry report",
    "growth report",
    "trade ideas",
    "statista",
    "indexbox",
    "tradingview",
    "finviz",
    "expected to reach us$",
    "2034",
    "2026-2034",
)

MARKET_INTELLIGENCE_KEYWORDS = (
    "price",
    "prices",
    "futures",
    "market",
    "sell",
    "buy",
    "bullish",
    "bearish",
    "risk",
    "hold",
    "stock",
    "farmer",
    "farmers",
    "rise",
    "rising",
    "fall",
    "falling",
    "outlook",
    "export",
    "exports",
)

WEATHER_KEYWORDS = (
    "weather",
    "rain",
    "rainfall",
    "humidity",
    "temperature",
    "wind",
    "crop",
    "crops",
    "harvest",
    "forecast",
)


class CoffeeRetriever:
    def __init__(
        self,
        embedder: EmbeddingService | None = None,
        vector_store: CoffeeVectorStore | None = None,
    ) -> None:
        self.embedder = embedder or EmbeddingService()
        self.vector_store = vector_store or CoffeeVectorStore()

    def available(self) -> bool:
        return self.vector_store.ensure_collection(self.embedder.dimension())

    def _embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embedder.embed_documents(texts)

    def _embed_query(self, query: str) -> list[float]:
        return self.embedder.embed_text(query)

    def search(self, query: str, top_k: int | None = None) -> list:
        if not self.available():
            return []
        try:
            requested_limit = top_k or settings.rag_top_k
            query_multiplier = 6 if (self._is_market_intelligence_query(query) or self._is_weather_query(query)) else 4
            candidate_limit = max(requested_limit * query_multiplier, 30 if query_multiplier == 6 else 20)
            response_points = self.vector_store.query(self._embed_query(query), candidate_limit)
            documents: list[Document] = []
            for point in response_points:
                payload = dict(point.payload or {})
                nested_metadata = payload.pop("metadata", {})
                if isinstance(nested_metadata, dict):
                    payload = {**nested_metadata, **payload}
                page_content = str(payload.pop("page_content", "")).strip()
                if not page_content:
                    continue
                if self._is_low_signal_document(payload, page_content):
                    continue
                payload["score"] = self._coerce_float(getattr(point, "score", 0.0))
                documents.append(Document(page_content=page_content, metadata=payload))
            reranked = self._rerank_documents(query, documents)
            return self._diversify_documents(query, reranked, requested_limit)
        except Exception as exc:
            logger.warning("Vector retrieval failed, returning no RAG context: {}", exc)
            return []

    def add_documents(self, documents: list) -> int:
        if not documents:
            return 0
        if not self.available():
            logger.warning("Skipping vector indexing because Qdrant is offline")
            return 0
        try:
            vectors = self._embed_documents([document.page_content for document in documents])
            return self.vector_store.upsert_documents(documents, vectors)
        except Exception as exc:
            logger.warning("Vector indexing failed, skipping document batch: {}", exc)
            return 0

    def _rerank_documents(self, query: str, documents: list[Document]) -> list[Document]:
        if not documents:
            return []

        recency_sensitive = self._is_recency_query(query)
        market_intelligence = self._is_market_intelligence_query(query)
        weather_focused = self._is_weather_query(query)
        raw_scores = [self._coerce_float(document.metadata.get("score")) for document in documents]
        min_score = min(raw_scores)
        max_score = max(raw_scores)
        ranked_documents: list[Document] = []

        # Blend semantic similarity with freshness and source quality so newer,
        # more trusted market intelligence rises without overwhelming relevance.
        if recency_sensitive:
            semantic_weight, freshness_weight, reliability_weight = 0.50, 0.35, 0.15
        else:
            semantic_weight, freshness_weight, reliability_weight = 0.68, 0.20, 0.12

        for document in documents:
            metadata = dict(document.metadata)
            semantic_score = self._normalize_semantic_score(
                self._coerce_float(metadata.get("score")),
                min_score,
                max_score,
            )
            freshness_score = self._freshness_score(metadata.get("published_at"), recency_sensitive)
            reliability_score = self._source_reliability_score(metadata)
            alignment_boost = self._query_alignment_boost(
                metadata,
                market_intelligence=market_intelligence,
                weather_focused=weather_focused,
            )
            rerank_score = (
                semantic_score * semantic_weight
                + freshness_score * freshness_weight
                + reliability_score * reliability_weight
                + alignment_boost
            )
            metadata["semantic_score"] = round(semantic_score, 4)
            metadata["freshness_score"] = round(freshness_score, 4)
            metadata["reliability_score"] = round(reliability_score, 4)
            metadata["alignment_boost"] = round(alignment_boost, 4)
            metadata["rerank_score"] = round(rerank_score, 4)
            ranked_documents.append(Document(page_content=document.page_content, metadata=metadata))

        if recency_sensitive:
            ranked_documents.sort(
                key=lambda document: (
                    self._published_timestamp(document.metadata.get("published_at")),
                    self._coerce_float(document.metadata.get("rerank_score")),
                    self._coerce_float(document.metadata.get("score")),
                ),
                reverse=True,
            )
        else:
            ranked_documents.sort(
                key=lambda document: (
                    self._coerce_float(document.metadata.get("rerank_score")),
                    self._published_timestamp(document.metadata.get("published_at")),
                    self._coerce_float(document.metadata.get("score")),
                ),
                reverse=True,
            )

        deduped_documents: list[Document] = []
        seen_signatures: set[tuple[str, str, str, str]] = set()
        for document in ranked_documents:
            signature = self._document_signature(document)
            if signature in seen_signatures:
                continue
            seen_signatures.add(signature)
            deduped_documents.append(document)
        return deduped_documents

    def _diversify_documents(self, query: str, documents: list[Document], limit: int) -> list[Document]:
        if len(documents) <= limit:
            return documents[:limit]

        target_sources = self._target_sources(query, documents)
        if not target_sources:
            return documents[:limit]

        source_buckets: dict[str, list[Document]] = {}
        for document in documents:
            source_buckets.setdefault(self._source_key(document), []).append(document)

        selected: list[Document] = []
        selected_ids: set[int] = set()
        while len(selected) < limit:
            progressed = False
            for source in target_sources:
                bucket = source_buckets.get(source) or []
                while bucket:
                    candidate = bucket.pop(0)
                    candidate_id = id(candidate)
                    if candidate_id in selected_ids:
                        continue
                    selected.append(candidate)
                    selected_ids.add(candidate_id)
                    progressed = True
                    break
                if len(selected) >= limit:
                    break
            if not progressed:
                break

        for document in documents:
            if len(selected) >= limit:
                break
            document_id = id(document)
            if document_id in selected_ids:
                continue
            selected.append(document)
            selected_ids.add(document_id)
        return selected[:limit]

    def _target_sources(self, query: str, documents: list[Document]) -> list[str]:
        available_sources = {self._source_key(document) for document in documents}
        lowered = query.lower()
        targets: list[str] = []

        if any(keyword in lowered for keyword in MARKET_INTELLIGENCE_KEYWORDS):
            targets.extend(
                [
                    "forecasting",
                    "futures",
                    "weather",
                    "news_rss",
                    "news_reuters",
                    "news_api",
                    "news_scraper",
                    "news_board",
                ]
            )
        elif any(keyword in lowered for keyword in WEATHER_KEYWORDS):
            targets.extend(["forecasting", "weather", "news_rss", "news_reuters", "futures"])

        if self._is_recency_query(query):
            for source in ("forecasting", "news_rss", "news_reuters", "news_api", "futures", "weather"):
                if source not in targets:
                    targets.append(source)

        return [source for source in targets if source in available_sources]

    def _source_key(self, document: Document) -> str:
        return str(document.metadata.get("source") or "").strip().lower()

    def _is_market_intelligence_query(self, query: str) -> bool:
        lowered = query.lower()
        return any(keyword in lowered for keyword in MARKET_INTELLIGENCE_KEYWORDS)

    def _is_weather_query(self, query: str) -> bool:
        lowered = query.lower()
        return any(keyword in lowered for keyword in WEATHER_KEYWORDS)

    def _query_alignment_boost(
        self,
        metadata: dict,
        *,
        market_intelligence: bool,
        weather_focused: bool,
    ) -> float:
        source = str(metadata.get("source") or "").strip().lower()
        record_type = str(metadata.get("record_type") or "").strip().lower()
        boost = 0.0

        if market_intelligence:
            if source == "futures":
                boost += 0.08
                if "snapshot" in record_type or "intelligence" in record_type:
                    boost += 0.02
            elif source == "forecasting":
                boost += 0.09
                if any(token in record_type for token in ("risk", "alert", "intelligence", "correlation")):
                    boost += 0.03
            elif source == "weather":
                boost += 0.05
            elif source.startswith("news") or source == "bootstrap_news":
                boost += 0.04

        if weather_focused and source == "weather":
            boost += 0.08
            if "forecast" in record_type:
                boost += 0.02
        if weather_focused and source == "forecasting" and "alert" in record_type:
            boost += 0.03

        return boost

    def _document_signature(self, document: Document) -> tuple[str, str, str, str]:
        metadata = document.metadata
        canonical_url = str(metadata.get("url") or metadata.get("source_url") or "").strip().lower()
        source = str(metadata.get("source") or "").strip().lower()
        title = str(metadata.get("title") or "").strip().lower()
        record_type = str(metadata.get("record_type") or "").strip().lower()
        market = str(metadata.get("market") or "").strip().lower()
        region = str(metadata.get("region") or "").strip().lower()
        snapshot_date = str(metadata.get("snapshot_date") or "").strip().lower()
        published_at = str(metadata.get("published_at") or "").strip().lower()
        if canonical_url:
            return canonical_url, title, record_type, source
        date_or_scope = snapshot_date or published_at[:10] or market or region
        return source, title, record_type, date_or_scope

    def _is_recency_query(self, query: str) -> bool:
        lowered = query.lower()
        return any(keyword in lowered for keyword in RECENCY_KEYWORDS)

    def _normalize_semantic_score(self, score: float, min_score: float, max_score: float) -> float:
        if max_score <= min_score:
            return 1.0 if score > 0 else 0.0
        normalized = (score - min_score) / (max_score - min_score)
        return max(0.0, min(normalized, 1.0))

    def _freshness_score(self, value, recency_sensitive: bool) -> float:
        published_ts = self._published_timestamp(value)
        if published_ts <= 0:
            return 0.25
        age_days = max(0.0, (datetime.now(timezone.utc).timestamp() - published_ts) / 86400)
        decay_window_days = 10 if recency_sensitive else 35
        return max(0.05, math.exp(-age_days / decay_window_days))

    def _source_reliability_score(self, metadata: dict) -> float:
        source_name = str(metadata.get("source") or "").strip().lower()
        channel = str(metadata.get("channel") or "").strip().lower()
        title = str(metadata.get("title") or "").strip().lower()
        url = str(metadata.get("url") or metadata.get("source_url") or "").strip().lower()
        domain = urlparse(url).netloc.lower()

        score = SOURCE_RELIABILITY_HINTS.get(source_name, 0.76)
        if channel in SOURCE_RELIABILITY_HINTS:
            score = max(score, SOURCE_RELIABILITY_HINTS[channel])

        for domain_hint, hint_score in DOMAIN_RELIABILITY_HINTS.items():
            if domain_hint in domain:
                score = max(score, hint_score)

        combined_text = " ".join(part for part in (source_name, channel, title, domain) if part)
        if "reuters" in combined_text:
            score = max(score, 0.96)
        if "coffee board" in combined_text or domain.endswith(".gov.in"):
            score = max(score, 0.98)
        if "global coffee platform" in combined_text:
            score = max(score, 0.94)
        return max(0.0, min(score, 1.0))

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

    def _is_low_signal_document(self, metadata: dict, page_content: str) -> bool:
        title = str(metadata.get("title") or "").strip().lower()
        summary = " ".join(page_content.split()).strip().lower()
        lowered = f"{title} {summary}"
        return any(term in lowered for term in LOW_SIGNAL_TERMS)

    def _coerce_float(self, value) -> float:
        try:
            return float(value or 0.0)
        except (TypeError, ValueError):
            return 0.0
