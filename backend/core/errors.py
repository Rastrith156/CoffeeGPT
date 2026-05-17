"""
core/errors.py
==============
Structured Enterprise Exception Hierarchy.
Replaces generic except blocks with strongly-typed operational domain failures.

ISSUE #1 FIX: Expanded exception hierarchy to cover all operational scenarios.
"""
from __future__ import annotations

from typing import Any


class PlatformError(Exception):
    """
    Base generic platform exception. Every specialized intelligence layer error
    derives from this base class to support standardized global HTTP formatting.
    """

    def __init__(self, message: str, status_code: int = 500, context: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.context = context or {}

    def __str__(self) -> str:
        ctx_str = f" | context={self.context}" if self.context else ""
        return f"[{self.__class__.__name__}] {self.message}{ctx_str}"


# ─── External API Errors ──────────────────────────────────────────────────────


class APIError(PlatformError):
    """
    Triggered when upstream external integration nodes (Barchart, OpenWeather, NewsAPI)
    timeout, return unparseable schemas, or disconnect unexpectedly.
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=502, context=context)


class NetworkError(APIError):
    """Network connectivity issues with external services."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, context=context)


class TimeoutError(APIError):
    """Request timeout from external services."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, context=context)


class RateLimitError(APIError):
    """External API rate limit exceeded."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, context=context)


# ─── Data Layer Errors ────────────────────────────────────────────────────────


class RetrievalError(PlatformError):
    """
    Triggered when vector engine collections (Qdrant) become unreachable, return
    empty payload indexes during hot query paths, or fail embedding alignments.
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=503, context=context)


class DatabaseError(PlatformError):
    """PostgreSQL connection or query failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=503, context=context)


class RedisError(PlatformError):
    """Redis connection, read, or write failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=503, context=context)


# ─── Streaming & Real-Time Errors ─────────────────────────────────────────────


class StreamingError(PlatformError):
    """
    Triggered when WebSocket subscription boundaries break, live ticker queues
    stall, or internal real-time memory event dispatchers encounter serialization faults.
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=500, context=context)


class WebSocketError(StreamingError):
    """WebSocket connection or communication failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, context=context)


class StreamStaleError(StreamingError):
    """Stream data is stale or heartbeat timeout exceeded."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, context=context)


class CircuitBreakerError(StreamingError):
    """Circuit breaker tripped due to consecutive failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, context=context)


# ─── LLM & Intelligence Errors ────────────────────────────────────────────────


class LLMError(PlatformError):
    """
    Triggered when language reasoning engines (LM Studio, local adapters) exhaust
    configured context buffers, return malformed generations, or fail heuristic grounding.
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=504, context=context)


class GenerationError(LLMError):
    """LLM generation failed or returned invalid output."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, context=context)


class ContextLengthError(LLMError):
    """LLM context length exceeded."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, context=context)


# ─── Ingestion & Processing Errors ────────────────────────────────────────────


class IngestionError(PlatformError):
    """Data ingestion pipeline failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=500, context=context)


class ValidationError(PlatformError):
    """Data validation or schema mismatch errors."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=400, context=context)


class TransformationError(IngestionError):
    """Data transformation or normalization failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, context=context)


# ─── Configuration & Initialization Errors ────────────────────────────────────


class ConfigurationError(PlatformError):
    """Invalid configuration or missing required settings."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=500, context=context)


class InitializationError(PlatformError):
    """Service or component initialization failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=500, context=context)


# ─── Authentication & Authorization Errors ────────────────────────────────────


class AuthenticationError(PlatformError):
    """Authentication failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=401, context=context)


class AuthorizationError(PlatformError):
    """Authorization/permission failures."""

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=403, context=context)
