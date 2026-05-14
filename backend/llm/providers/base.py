"""
llm/providers/base.py
=====================
Defines the protocol and base interface for all LLM providers.
Ensures identical method signatures regardless of the upstream model.
"""
from __future__ import annotations

from typing import Any, List, Optional, Protocol


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
        """Generate text completion from prompt."""
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
