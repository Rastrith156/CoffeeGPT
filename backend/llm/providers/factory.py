"""
llm/providers/factory.py
========================
Task 2 — Real multi-provider factory.

Reads LLM_PROVIDER env var and returns the correct implementation.
Registered providers: lmstudio | anthropic | openai | ollama

Each provider implements LLMProviderProtocol (generate, generate_json, stream_generate).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.config import settings
from core.logger import logger
from llm.providers.base import LLMProviderProtocol

if TYPE_CHECKING:
    pass


def get_provider(provider_name: str | None = None) -> LLMProviderProtocol:
    """
    Instantiate and return the configured LLM provider.

    Provider selection order:
      1. explicit `provider_name` argument (for testing / per-request override)
      2. LLM_PROVIDER env var (settings.llm_provider)

    Raises ValueError with a clear message for unknown providers.
    """
    name = (provider_name or settings.llm_provider).lower().strip()
    logger.debug("LLM factory: resolving provider={!r}", name)

    if name == "lmstudio":
        from llm.providers.lmstudio import LMStudioProvider
        return LMStudioProvider()

    if name == "anthropic":
        from llm.providers.anthropic import AnthropicProvider
        return AnthropicProvider()

    if name in ("openai", "azure"):
        from llm.providers.openai_provider import OpenAIProvider
        return OpenAIProvider()

    if name == "ollama":
        from llm.providers.ollama import OllamaProvider
        return OllamaProvider()

    raise ValueError(
        f"Unsupported LLM provider: {name!r}. "
        f"Available: lmstudio | anthropic | openai | ollama"
    )
