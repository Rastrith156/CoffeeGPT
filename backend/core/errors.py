"""
core/errors.py
==============
Structured Enterprise Exception Hierarchy.
Replaces generic except blocks with strongly-typed operational domain failures.
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


class APIError(PlatformError):
    """
    Triggered when upstream external integration nodes (Barchart, OpenWeather, NewsAPI)
    timeout, return unparseable schemas, or disconnect unexpectedly.
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=502, context=context)


class RetrievalError(PlatformError):
    """
    Triggered when vector engine collections (Qdrant) become unreachable, return
    empty payload indexes during hot query paths, or fail embedding alignments.
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=503, context=context)


class StreamingError(PlatformError):
    """
    Triggered when WebSocket subscription boundaries break, live ticker queues
    stall, or internal real-time memory event dispatchers encounter serialization faults.
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=500, context=context)


class LLMError(PlatformError):
    """
    Triggered when language reasoning engines (LM Studio, local adapters) exhaust
    configured context buffers, return malformed generations, or fail heuristic grounding.
    """

    def __init__(self, message: str, context: dict[str, Any] | None = None) -> None:
        super().__init__(message, status_code=504, context=context)
