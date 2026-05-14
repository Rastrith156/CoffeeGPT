"""
llm/providers/factory.py
========================
Factory for LLM providers.
Enables dynamic switching between local models and external APIs via configuration.
"""
from __future__ import annotations

from core.config import settings
from llm.providers.base import LLMProviderProtocol
from llm.providers.lmstudio import LMStudioProvider

_PROVIDERS = {
    "lmstudio": LMStudioProvider,
    # "openai": OpenAIProvider,  # Future expansion
    # "gemini": GeminiProvider,  # Future expansion
}


def get_provider(provider_name: str | None = None) -> LLMProviderProtocol:
    """
    Get an instance of the configured LLM provider.
    """
    name = provider_name or settings.llm_provider
    provider_class = _PROVIDERS.get(name.lower())

    if provider_class is None:
        raise ValueError(
            f"Unsupported LLM provider: {name}. "
            f"Available providers: {list(_PROVIDERS.keys())}"
        )

    return provider_class()
