from __future__ import annotations

import json

from rag.chunker import DocumentChunker
from rag.retriever import CoffeeRetriever


class RAGPipeline:
    def __init__(
        self,
        chunker: DocumentChunker | None = None,
        retriever: CoffeeRetriever | None = None,
    ) -> None:
        self.chunker = chunker or DocumentChunker()
        self.retriever = retriever or CoffeeRetriever()

    def index_records(self, records: list[dict]) -> int:
        documents = self._build_documents(records)
        return self.retriever.add_documents(documents)

    def _build_documents(self, records: list[dict]):
        items = []
        for record in records:
            metadata = {
                "source": record.get("metadata", {}).get("source", "unknown"),
                "title": record.get("title"),
                "record_type": record.get("record_type"),
            }
            content = record.get("content") or json.dumps(record.get("raw", record), indent=2, default=str)
            items.append({"text": content, "metadata": metadata})
        return self.chunker.chunk_many(items)
