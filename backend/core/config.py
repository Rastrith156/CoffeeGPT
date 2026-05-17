from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
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
    debug: bool = Field(default=False, alias="APP_DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    secret_key: str = Field(default="change_me", alias="SECRET_KEY")

    # ── Database ────────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql://coffeegpt_user:password@localhost:5432/coffeegpt",
        alias="DATABASE_URL",
    )

    # ── Qdrant ──────────────────────────────────────────────────────────────
    qdrant_host: str = Field(default="localhost", alias="QDRANT_HOST")
    qdrant_port: int = Field(default=6333, alias="QDRANT_PORT")
    qdrant_collection: str = Field(default="coffee_intelligence", alias="QDRANT_COLLECTION")
    embedding_vector_size: int = Field(default=384, alias="EMBEDDING_VECTOR_SIZE")

    # ── Redis / Celery ───────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_broker_url: str = Field(default="redis://localhost:6379/0", alias="CELERY_BROKER_URL")
    celery_result_backend: str = Field(default="redis://localhost:6379/0", alias="CELERY_RESULT_BACKEND")
    use_celery_for_ingestion: bool = Field(default=False, alias="USE_CELERY_FOR_INGESTION")

    # ── LLM (primary) ────────────────────────────────────────────────────────
    lmstudio_base_url: str = Field(default="http://localhost:1234", alias="LMSTUDIO_BASE_URL")
    lmstudio_api_token: str = Field(default="", alias="LMSTUDIO_API_TOKEN")
    llm_model: str = Field(default="dolphin-2.9-llama3-8b-256k-smashed", alias="LLM_MODEL")
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    llm_max_output_tokens: int = Field(default=700, alias="LLM_MAX_OUTPUT_TOKENS")
    llm_context_length: int = Field(default=8192, alias="LLM_CONTEXT_LENGTH")
    llm_timeout_seconds: float = Field(default=60, alias="LLM_TIMEOUT_SECONDS")
    embedding_model: str = Field(default="all-MiniLM-L6-v2", alias="EMBEDDING_MODEL")

    # ── LLM Provider routing (Task 2) ────────────────────────────────────────
    llm_provider: str = Field(default="lmstudio", alias="LLM_PROVIDER")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    anthropic_model: str = Field(default="claude-3-5-haiku-20241022", alias="ANTHROPIC_MODEL")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_model: str = Field(default="llama3", alias="OLLAMA_MODEL")

    # ── External APIs ────────────────────────────────────────────────────────
    openweather_api_key: str = Field(default="", alias="OPENWEATHER_API_KEY")
    newsapi_key: str = Field(default="", alias="NEWSAPI_KEY")
    ico_api_key: str = Field(default="", alias="ICO_API_KEY")
    barchart_api_key: str = Field(default="", alias="BARCHART_API_KEY")

    # ── RAG & Ingestion ──────────────────────────────────────────────────────
    chunk_size: int = Field(default=1000, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=200, alias="CHUNK_OVERLAP")
    rag_top_k: int = Field(default=5, alias="RAG_TOP_K")
    weather_forecast_days: int = Field(default=7, alias="WEATHER_FORECAST_DAYS")
    weather_poll_interval_seconds: int = Field(default=21600, alias="WEATHER_POLL_INTERVAL_SECONDS")
    futures_poll_interval_seconds: int = Field(default=21600, alias="FUTURES_POLL_INTERVAL_SECONDS")

    # ── HOT LAYER streaming ──────────────────────────────────────────────────
    stream_interval_seconds: int = Field(default=30, alias="STREAM_INTERVAL_SECONDS")
    monitor_interval_seconds: int = Field(default=15, alias="MONITOR_INTERVAL_SECONDS")
    intelligence_loop_interval_seconds: int = Field(default=120, alias="INTELLIGENCE_LOOP_INTERVAL_SECONDS")
    spike_threshold_pct: float = Field(default=2.0, alias="SPIKE_THRESHOLD_PCT")
    high_volatility_threshold_pct: float = Field(default=2.5, alias="HIGH_VOLATILITY_THRESHOLD_PCT")
    redis_price_ttl_seconds: int = Field(default=60, alias="REDIS_PRICE_TTL_SECONDS")
    redis_alert_ttl_seconds: int = Field(default=300, alias="REDIS_ALERT_TTL_SECONDS")

    # ── Stream provider URLs (all external endpoints in one place) ───────────
    barchart_quote_url: str = Field(
        default="https://ondemand.websol.barchart.com/getQuote.json",
        alias="BARCHART_QUOTE_URL",
    )
    barchart_overview_url: str = Field(
        default="https://www.barchart.com/futures/quotes/RM*0/overview",
        alias="BARCHART_OVERVIEW_URL",
    )
    barchart_arabica_symbols: str = Field(default="KCY00,KC*1", alias="BARCHART_ARABICA_SYMBOLS")
    stream_user_agent: str = Field(
        default="Mozilla/5.0 (compatible; CoffeeGPT-Stream/1.0)",
        alias="STREAM_USER_AGENT",
    )

    # ── Exponential backoff & circuit breaker ────────────────────────────────
    stream_backoff_base_seconds: float = Field(default=5.0, alias="STREAM_BACKOFF_BASE_SECONDS")
    stream_backoff_max_seconds: float = Field(default=300.0, alias="STREAM_BACKOFF_MAX_SECONDS")
    stream_circuit_breaker_threshold: int = Field(default=5, alias="STREAM_CIRCUIT_BREAKER_THRESHOLD")
    stream_degraded_interval_seconds: int = Field(default=120, alias="STREAM_DEGRADED_INTERVAL_SECONDS")

    # ── Stream health & freshness ────────────────────────────────────────────
    stream_stale_threshold_seconds: int = Field(default=90, alias="STREAM_STALE_THRESHOLD_SECONDS")
    stream_health_report_interval_seconds: int = Field(default=30, alias="STREAM_HEALTH_REPORT_INTERVAL_SECONDS")

    # ── Hot-state snapshot persistence ───────────────────────────────────────
    snapshot_interval_seconds: int = Field(default=300, alias="SNAPSHOT_INTERVAL_SECONDS")  # 5 min
    snapshot_retention_days: int = Field(default=30, alias="SNAPSHOT_RETENTION_DAYS")


    # ── Security & Auth (Task 3) ──────────────────────────────────────────────
    api_keys: list[str] = Field(default_factory=list, alias="API_KEYS")
    auth_enabled: bool = Field(default=True, alias="AUTH_ENABLED")
    rate_limit_per_minute: int = Field(default=100, alias="RATE_LIMIT_PER_MINUTE")
    trace_header_name: str = Field(default="X-Trace-ID", alias="TRACE_HEADER_NAME")

    # JWT configuration
    jwt_secret_key: str = Field(default="change_me_jwt_secret_32chars_min!", alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(default=15, alias="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(default=7, alias="REFRESH_TOKEN_EXPIRE_DAYS")

    # Per-endpoint rate limits (req/min)
    rate_limit_chat: int = Field(default=20, alias="RATE_LIMIT_CHAT")
    rate_limit_market: int = Field(default=60, alias="RATE_LIMIT_MARKET")
    rate_limit_ingestion: int = Field(default=5, alias="RATE_LIMIT_INGESTION")
    rate_limit_auth: int = Field(default=10, alias="RATE_LIMIT_AUTH")

    run_background_tasks: bool = Field(default=True, alias="RUN_BACKGROUND_TASKS")
    rag_retrieval_multiplier: int = Field(default=2, alias="RAG_RETRIEVAL_MULTIPLIER")

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
    weather_regions: list[str] = Field(
        default_factory=lambda: [
            "Chikmagalur", "Kodagu", "Hassan", "Sakleshpur",
            "Sul de Minas", "Cerrado Mineiro", "Espirito Santo",
            "Dak Lak", "Lam Dong", "Gia Lai",
        ],
        alias="WEATHER_REGIONS",
    )

    # ── OpenTelemetry (Task 5) ────────────────────────────────────────────────
    otel_enabled: bool = Field(default=False, alias="OTEL_ENABLED")
    otel_service_name: str = Field(default="coffeegpt-backend", alias="OTEL_SERVICE_NAME")
    otel_exporter_endpoint: str = Field(default="http://localhost:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT")

    # ── Validators ────────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def _validate_production_safety(self) -> "Settings":
        """Crash early if critical configs are insecure."""
        if self.secret_key == "change_me":
            raise RuntimeError("FATAL: secret_key cannot be 'change_me'. Please set a secure SECRET_KEY in your environment.")

        if self.environment.lower() == "production":
            if "*" in self.cors_origins:
                raise ValueError(
                    "CORS_ORIGINS cannot be ['*'] in production. "
                    "Set explicit allowed origins in CORS_ORIGINS env var."
                )
            if self.secret_key in ("change_me", "change_me_to_a_secure_random_string"):
                raise ValueError("SECRET_KEY must be changed from default in production.")
            if self.jwt_secret_key.startswith("change_me"):
                raise ValueError("JWT_SECRET_KEY must be set to a secure value in production.")
        return self

    @field_validator("llm_model", mode="before")
    @classmethod
    def _warn_non_standard_model(cls, v: str) -> str:
        """
        Fix #13: emit a clear warning when a model name looks like it refers to
        a locally-quantised or personal model that contributors may not have.

        We detect this heuristically: the default dolphin model name is very
        specific and will fail immediately on any machine that doesn't have it.
        The validator does NOT reject the value — it just warns loudly so
        contributors see the issue before runtime.
        """
        import logging as _logging
        _KNOWN_STANDARD_PREFIXES = (
            "gpt-", "claude-", "llama", "mistral", "gemma",
            "phi-", "falcon", "qwen", "internlm", "deepseek",
        )
        v_lower = v.lower()
        is_standard = any(v_lower.startswith(p) for p in _KNOWN_STANDARD_PREFIXES)
        is_local_path = "/" in v or "\\" in v
        # The default dolphin model is our canonical "looks personal" example
        is_personal_default = "dolphin" in v_lower or "smashed" in v_lower
        if not is_standard or is_local_path or is_personal_default:
            _logging.getLogger("coffeegpt.config").warning(
                "LLM_MODEL=%r looks like a locally-quantised or personal model name. "
                "Contributors who do not have this model in LM Studio will see a "
                "connection error at startup. Set LLM_MODEL in your .env to override. "
                "See .env.example for guidance.",
                v,
            )
        return v

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

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
