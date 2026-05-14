"""
llm/providers/base.py
=====================
Protocol and base interface for all LLM providers.

Task 2: Added stream_generate() async generator to protocol —
        yields str tokens for real token-by-token SSE streaming.
"""
from __future__ import annotations

from typing import Any, AsyncGenerator, Optional, Protocol, runtime_checkable


@runtime_checkable
class LLMProviderProtocol(Protocol):
    """
    Structural protocol for LLM providers.
    Any class implementing these methods can be used by the platform.
    """

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """Generate full text completion from prompt."""
        ...

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate structured JSON response."""
        ...

    async def stream_generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        """
        Stream text tokens one at a time.
        Yields individual string chunks (tokens) as they arrive from the model.
        Callers must async-iterate: `async for token in provider.stream_generate(...):`
        """
        ...


class ProviderError(Exception):
    """Raised when an LLM provider encounters an unrecoverable error."""
    def __init__(self, provider: str, message: str, status_code: int | None = None) -> None:
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"[{provider}] {message}")


class RateLimitError(ProviderError):
    """Raised when the provider returns HTTP 429 / 529."""
    pass
