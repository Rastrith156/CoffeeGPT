from __future__ import annotations

from sentence_transformers import SentenceTransformer

from core.config import settings

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
_MODEL_CACHE: dict[str, SentenceTransformer] = {}


class EmbeddingService:
    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = (model_name or settings.embedding_model or DEFAULT_EMBEDDING_MODEL).strip()

    def _get_model(self) -> SentenceTransformer:
        model = _MODEL_CACHE.get(self.model_name)
        if model is None:
            model = SentenceTransformer(self.model_name, device="cpu")
            _MODEL_CACHE[self.model_name] = model
        return model

    def dimension(self) -> int:
        model = self._get_model()
        if hasattr(model, "get_embedding_dimension"):
            dimension = model.get_embedding_dimension()
        else:
            dimension = model.get_sentence_embedding_dimension()
        return int(dimension or settings.embedding_vector_size)

    def embed_text(self, text: str) -> list[float]:
        model = self._get_model()
        embedding = model.encode(
            self._normalize_text(text),
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return embedding.tolist()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._get_model()
        embeddings = model.encode(
            [self._normalize_text(text) for text in texts],
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return embeddings.tolist()

    def _normalize_text(self, text: str) -> str:
        cleaned = text.strip()
        return cleaned or " "


def get_embedding_model(model_name: str | None = None) -> SentenceTransformer:
    return EmbeddingService(model_name)._get_model()


def embed_text(text: str, model_name: str | None = None) -> list[float]:
    return EmbeddingService(model_name).embed_text(text)


def embed_documents(texts: list[str], model_name: str | None = None) -> list[list[float]]:
    return EmbeddingService(model_name).embed_documents(texts)
