from __future__ import annotations

from langchain_core.documents import Document
from rag.embedder import EmbeddingService
from rag.store import CoffeeVectorStore

from core.config import settings
from core.logger import logger


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
            candidate_limit = max(requested_limit, 15)
            response_points = self.vector_store.query(self._embed_query(query), candidate_limit)
            documents: list[Document] = []
            seen_signatures: set[tuple[str, str, str, str]] = set()
            for point in response_points:
                payload = dict(point.payload or {})
                nested_metadata = payload.pop("metadata", {})
                if isinstance(nested_metadata, dict):
                    payload = {**nested_metadata, **payload}
                page_content = str(payload.pop("page_content", "")).strip()
                if not page_content:
                    continue
                signature = (
                    str(payload.get("source", "")),
                    str(payload.get("title", "")),
                    str(payload.get("record_type", "")),
                    page_content,
                )
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
                payload["score"] = getattr(point, "score", None)
                documents.append(Document(page_content=page_content, metadata=payload))
            return documents[:requested_limit]
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
