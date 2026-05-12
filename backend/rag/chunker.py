from __future__ import annotations

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from core.config import settings


class DocumentChunker:
    def __init__(self) -> None:
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            separators=["\n\n", "\n", ". ", " ", ""],
        )

    def chunk(self, text: str, metadata: dict | None = None) -> list[Document]:
        return self.splitter.create_documents(texts=[text], metadatas=[metadata or {}])

    def chunk_many(self, items: list[dict]) -> list[Document]:
        documents: list[Document] = []
        for item in items:
            documents.extend(self.chunk(item["text"], item.get("metadata")))
        return documents
