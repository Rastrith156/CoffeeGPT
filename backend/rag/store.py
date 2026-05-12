from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, FieldCondition, Filter, MatchValue, PointStruct, VectorParams

from core.config import settings
from core.logger import logger


class CoffeeVectorStore:
    def __init__(
        self,
        client: QdrantClient | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.client = client
        self.collection_name = collection_name or settings.qdrant_collection
        self._online = False

    def available(self) -> bool:
        try:
            self._get_client().get_collections()
            self._online = True
        except Exception as exc:
            logger.warning("Qdrant unavailable, continuing without vector search: {}", exc)
            self._online = False
        return self._online

    def ensure_collection(self, vector_size: int) -> bool:
        try:
            client = self._get_client()
            collections = [collection.name for collection in client.get_collections().collections]
            if self.collection_name not in collections:
                client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=vector_size,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection {}", self.collection_name)
            self._online = True
        except Exception as exc:
            logger.warning("Qdrant unavailable, continuing without vector search: {}", exc)
            self._online = False
        return self._online

    def query(self, query_vector: list[float], limit: int) -> list:
        response = self._get_client().query_points(
            collection_name=self.collection_name,
            query=query_vector,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return getattr(response, "points", []) or []

    def upsert_documents(self, documents: list, vectors: list[list[float]]) -> int:
        if len(documents) != len(vectors):
            raise ValueError("Document and vector counts must match before Qdrant upsert.")

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
        self._get_client().upsert(collection_name=self.collection_name, points=points, wait=True)
        logger.info("Indexed {} document chunks into Qdrant", len(points))
        return len(points)

    def delete_by_source(self, source: str) -> None:
        self._get_client().delete(
            collection_name=self.collection_name,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="source",
                        match=MatchValue(value=source),
                    )
                ]
            ),
            wait=True,
        )
        logger.info("Deleted existing Qdrant points for source {}", source)

    def _get_client(self) -> QdrantClient:
        if self.client is None:
            self.client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        return self.client

    def _document_id(self, document) -> str:
        source = str(document.metadata.get("source", ""))
        title = str(document.metadata.get("title", ""))
        record_type = str(document.metadata.get("record_type", ""))
        seed = "\n".join([source, title, record_type, document.page_content])
        return str(uuid5(NAMESPACE_URL, seed))
