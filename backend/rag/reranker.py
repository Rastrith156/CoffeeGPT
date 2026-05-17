from typing import Any
import os
from langchain_core.documents import Document
from core.logger import logger
from core.config import settings

class RerankerService:
    def __init__(self):
        self.provider = getattr(settings, "reranker_provider", "local")
        self.cohere_client = None
        self.cross_encoder = None
        
        if self.provider == "cohere":
            api_key = getattr(settings, "cohere_api_key", os.environ.get("COHERE_API_KEY"))
            if api_key:
                import cohere
                self.cohere_client = cohere.Client(api_key)
            else:
                logger.warning("Cohere API key missing, falling back to local heuristic reranking.")
                self.provider = "local"
        elif self.provider == "bge":
            try:
                from sentence_transformers import CrossEncoder
                self.cross_encoder = CrossEncoder('BAAI/bge-reranker-base')
            except ImportError:
                logger.warning("sentence_transformers not installed, falling back to local heuristic reranking.")
                self.provider = "local"

    def rerank(self, query: str, documents: list[Document], top_k: int) -> list[Document]:
        if not documents:
            return []
            
        if self.provider == "cohere" and self.cohere_client:
            return self._rerank_cohere(query, documents, top_k)
        elif self.provider == "bge" and self.cross_encoder:
            return self._rerank_bge(query, documents, top_k)
            
        # Fallback to returning them un-reranked (retriever will apply heuristics)
        return documents[:top_k]

    def _rerank_cohere(self, query: str, documents: list[Document], top_k: int) -> list[Document]:
        try:
            texts = [doc.page_content for doc in documents]
            response = self.cohere_client.rerank(
                query=query,
                documents=texts,
                top_n=top_k,
                model="rerank-english-v3.0"
            )
            
            reranked = []
            for result in response.results:
                doc = documents[result.index]
                # Update score with Cohere's relevance score
                doc.metadata["cohere_relevance"] = result.relevance_score
                reranked.append(doc)
            return reranked
        except Exception as e:
            logger.error(f"Cohere reranking failed: {e}")
            return documents[:top_k]

    def _rerank_bge(self, query: str, documents: list[Document], top_k: int) -> list[Document]:
        try:
            pairs = [[query, doc.page_content] for doc in documents]
            scores = self.cross_encoder.predict(pairs)
            
            # Combine docs with scores
            doc_scores = list(zip(documents, scores))
            doc_scores.sort(key=lambda x: x[1], reverse=True)
            
            reranked = []
            for doc, score in doc_scores[:top_k]:
                doc.metadata["bge_score"] = float(score)
                reranked.append(doc)
            return reranked
        except Exception as e:
            logger.error(f"BGE reranking failed: {e}")
            return documents[:top_k]
