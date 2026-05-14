"""
llm/providers/lmstudio.py
=========================
LM Studio provider implementation.
Wraps the existing LMStudioClient to satisfy the LLMProviderProtocol.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from core.config import settings
from llm.providers.base import LLMProviderProtocol
from services.lmstudio_client import LMStudioClient


class LMStudioProvider:
    """
    Adapter for LM Studio or any OpenAI-compatible local API.
    """

    def __init__(self, client: Optional[LMStudioClient] = None) -> None:
        self.client = client or LMStudioClient()
        self.model = settings.llm_model

    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        """Generate text completion."""
        # Note: LMStudioClient.chat handles temperature and max_tokens via settings defaults,
        # but we could pass them if we modify chat() or handle them here.
        # For now, we use the client's defaults which read from settings.

        result = await self.client.chat(
            model=self.model,
            user_input=prompt,
            system_prompt=system_prompt,
        )
        return result.text

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate structured JSON response."""
        # Ensure we ask for JSON in the prompt if not already there
        enhanced_prompt = prompt
        if "json" not in prompt.lower():
            enhanced_prompt += "\n\nResponse must be a valid JSON object."

        text = await self.generate(
            enhanced_prompt,
            system_prompt=system_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )

        try:
            # Clean up potential markdown blocks if LLM included them
            cleaned = text.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Failed to parse LLM response as JSON: {exc}\nRaw response: {text}")
