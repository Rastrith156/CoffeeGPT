"""
llm/providers/anthropic.py
==========================
Task 2 — Anthropic Claude provider via raw httpx (no SDK — no new deps).

Features:
  - generate()       → blocking full completion
  - generate_json()  → JSON-coerced completion
  - stream_generate()→ token-by-token SSE from Anthropic Messages API
  - Tenacity: 3 retries, exponential backoff (1s→8s), jitter
  - Exception mapping: 429/529 → RateLimitError, 5xx → ProviderError
"""
from __future__ import annotations

import json
import re
from typing import Any, AsyncGenerator, Optional

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    before_sleep_log,
)

from core.config import settings
from core.logger import logger
from llm.providers.base import ProviderError, RateLimitError

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"

# Exceptions that are worth retrying
_RETRYABLE = (httpx.TimeoutException, httpx.NetworkError, ProviderError)


def _map_status(status_code: int, text: str) -> ProviderError:
    """Map Anthropic HTTP status codes to typed exceptions."""
    if status_code in (429, 529):
        return RateLimitError("anthropic", f"Rate limited ({status_code}): {text}", status_code)
    return ProviderError("anthropic", f"HTTP {status_code}: {text}", status_code)


class AnthropicProvider:
    """
    Anthropic Claude provider implementing LLMProviderProtocol.
    Uses raw httpx — no anthropic SDK needed.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_key = api_key or settings.anthropic_api_key
        self._model = model or settings.anthropic_model
        self._timeout = timeout or settings.llm_timeout_seconds
        if not self._api_key:
            raise ProviderError("anthropic", "ANTHROPIC_API_KEY is not set")

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }

    def _build_body(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens or settings.llm_max_output_tokens,
            "temperature": temperature if temperature is not None else settings.llm_temperature,
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }
        if system_prompt:
            body["system"] = system_prompt
        return body

    # ── generate ─────────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        before_sleep=before_sleep_log(logger, "WARNING"),  # type: ignore[arg-type]
        reraise=True,
    )
    async def generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> str:
        body = self._build_body(prompt, system_prompt, temperature, max_tokens, stream=False)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(ANTHROPIC_API_URL, headers=self._headers(), json=body)
            if resp.status_code != 200:
                raise _map_status(resp.status_code, resp.text[:300])
            data = resp.json()
            return data["content"][0]["text"]

    # ── generate_json ─────────────────────────────────────────────────────────

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        enhanced = prompt if "json" in prompt.lower() else prompt + "\n\nRespond with a valid JSON object only."
        text = await self.generate(enhanced, system_prompt, temperature, max_tokens, **kwargs)
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"AnthropicProvider: JSON parse error: {exc}\nRaw: {text}") from exc

    # ── stream_generate ───────────────────────────────────────────────────────

    async def stream_generate(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> AsyncGenerator[str, None]:
        body = self._build_body(prompt, system_prompt, temperature, max_tokens, stream=True)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            async with client.stream("POST", ANTHROPIC_API_URL, headers=self._headers(), json=body) as resp:
                if resp.status_code != 200:
                    content = await resp.aread()
                    raise _map_status(resp.status_code, content.decode()[:300])
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    # Anthropic SSE event types
                    etype = event.get("type", "")
                    if etype == "content_block_delta":
                        delta = event.get("delta", {})
                        token = delta.get("text", "")
                        if token:
                            yield token
                    elif etype == "message_stop":
                        break
                    elif etype == "error":
                        err = event.get("error", {})
                        raise ProviderError("anthropic", str(err))
