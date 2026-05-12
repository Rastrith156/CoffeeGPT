from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]

if (BACKEND_ROOT / "data").exists():
    PROJECT_ROOT = BACKEND_ROOT
elif (BACKEND_ROOT.parent / "data").exists():
    PROJECT_ROOT = BACKEND_ROOT.parent
else:
    PROJECT_ROOT = BACKEND_ROOT.parent

ENV_FILE = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="CoffeeGPT Intelligence Platform", alias="APP_NAME")
    app_version: str = Field(default="1.0.0", alias="APP_VERSION")
    api_prefix: str = Field(default="/api/v1", alias="API_PREFIX")
    environment: str = Field(default="development", alias="ENVIRONMENT")
    debug: bool = Field(default=True, alias="APP_DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    secret_key: str = Field(default="change_me", alias="SECRET_KEY")

    database_url: str = Field(
        default="postgresql://coffeegpt_user:password@localhost:5432/coffeegpt",
        alias="DATABASE_URL",
    )

    qdrant_host: str = Field(default="localhost", alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, alias="QDRANT_PORT")
    qdrant_collection: str = Field(default="coffee_intelligence", alias="QDRANT_COLLECTION")
    embedding_vector_size: int = Field(default=384, alias="EMBEDDING_VECTOR_SIZE")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/0", alias="CELERY_RESULT_BACKEND")
    use_celery_for_ingestion: bool = Field(default=False, alias="USE_CELERY_FOR_INGESTION")

    lmstudio_base_url: str = Field(default="http://localhost:1234", alias="LMSTUDIO_BASE_URL")
    lmstudio_api_token: str = Field(default="", alias="LMSTUDIO_API_TOKEN")
    llm_model: str = Field(default="dolphin-2.9-llama3-8b-256k-smashed", alias="LLM_MODEL")
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    llm_max_output_tokens: int = Field(default=700, alias="LLM_MAX_OUTPUT_TOKENS")
    llm_context_length: int = Field(default=8192, alias="LLM_CONTEXT_LENGTH")
    llm_timeout_seconds: float = Field(default=60, alias="LLM_TIMEOUT_SECONDS")
    embedding_model: str = Field(default="all-MiniLM-L6-v2", alias="EMBEDDING_MODEL")

    openweather_api_key: str = Field(default="", alias="OPENWEATHER_API_KEY")
    newsapi_key: str = Field(default="", alias="NEWSAPI_KEY")
    ico_api_key: str = Field(default="", alias="ICO_API_KEY")

    chunk_size: int = Field(default=1000, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=200, alias="CHUNK_OVERLAP")
    rag_top_k: int = Field(default=5, alias="RAG_TOP_K")

    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        alias="CORS_ORIGINS",
    )
    default_regions: list[str] = Field(
        default_factory=lambda: ["Yirgacheffe", "Sidama", "Minas Gerais", "Huila"],
        alias="DEFAULT_REGIONS",
    )

    @property
    def backend_root(self) -> Path:
        return BACKEND_ROOT

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def data_root(self) -> Path:
        return self.project_root / "data"

    @property
    def raw_data_dir(self) -> Path:
        return self.data_root / "raw"

    @property
    def processed_data_dir(self) -> Path:
        return self.data_root / "processed"

    @property
    def embeddings_data_dir(self) -> Path:
        return self.data_root / "embeddings"

    @property
    def logs_root(self) -> Path:
        return self.backend_root / "logs"

    def ensure_directories(self) -> None:
        for path in (
            self.raw_data_dir,
            self.processed_data_dir,
            self.embeddings_data_dir,
            self.logs_root,
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
