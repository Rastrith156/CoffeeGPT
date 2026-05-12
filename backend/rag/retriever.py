from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from langchain_core.documents import Document
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from rag.embedder import EmbeddingService

from core.config import settings
from core.logger import logger


class CoffeeRetriever:
    def __init__(self, embedder: EmbeddingService | None = None) -> None:
        self.client = None
        self.embedder = embedder or EmbeddingService()
        self._online = False

    def available(self) -> bool:
        if not self._online:
            self._ensure_collection()
        return self._online

    def _get_client(self) -> QdrantClient:
        if self.client is None:
            self.client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        return self.client

    def _ensure_collection(self) -> None:
        try:
            client = self._get_client()
            collections = [collection.name for collection in client.get_collections().collections]
            if settings.qdrant_collection not in collections:
                client.create_collection(
                    collection_name=settings.qdrant_collection,
                    vectors_config=VectorParams(
                        size=self.embedder.dimension(),
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection {}", settings.qdrant_collection)
            self._online = True
        except Exception as exc:
            logger.warning("Qdrant unavailable, continuing without vector search: {}", exc)
            self._online = False

    def _embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.embedder.embed_documents(texts)

    def _embed_query(self, query: str) -> list[float]:
        return self.embedder.embed_text(query)

    def search(self, query: str, top_k: int | None = None) -> list:
        if not self.available():
            return []
        try:
            response = self._get_client().query_points(
                collection_name=settings.qdrant_collection,
                query=self._embed_query(query),
                limit=top_k or settings.rag_top_k,
                with_payload=True,
                with_vectors=False,
            )
            documents: list[Document] = []
            seen_signatures: set[tuple[str, str, str, str]] = set()
            for point in getattr(response, "points", []) or []:
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
            return documents
        except Exception as exc:
            self._online = False
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
            points = [
                PointStruct(
                    id=self._document_id(document),
                    vector=vector,
                    payload={
                        "page_content": document.page_content,
                        **document.metadata,
                    },
                )
                for document, vector in zip(documents, vectors, strict=False)
            ]
            self._get_client().upsert(collection_name=settings.qdrant_collection, points=points, wait=True)
            logger.info("Indexed {} document chunks into Qdrant", len(points))
            return len(points)
        except Exception as exc:
            self._online = False
            logger.warning("Vector indexing failed, skipping document batch: {}", exc)
            return 0

    def _document_id(self, document) -> str:
        source = str(document.metadata.get("source", ""))
        title = str(document.metadata.get("title", ""))
        record_type = str(document.metadata.get("record_type", ""))
        seed = "\n".join([source, title, record_type, document.page_content])
        return str(uuid5(NAMESPACE_URL, seed))
