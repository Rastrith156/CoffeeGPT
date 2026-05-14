"""
llm/providers/openai_provider.py
=================================
Task 2 — OpenAI (and OpenAI-compatible: Azure, LMStudio, etc.) provider.

Works with any API that implements the OpenAI chat-completions contract:
  POST /chat/completions  { model, messages, stream, temperature, max_tokens }

Features:
  - generate()        → full completion
  - generate_json()   → JSON-coerced completion (response_format: json_object)
  - stream_generate() → token-by-token SSE
  - Tenacity: 3 retries, exponential backoff, 429 → RateLimitError
  - Bearer-token auth; configurable base_url for Azure / self-hosted use
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
from llm.providers.base import LLMProviderProtocol, ProviderError, RateLimitError

_RETRYABLE = (httpx.TimeoutException, httpx.NetworkError, ProviderError)


def _map_status(status_code: int, text: str) -> ProviderError:
    if status_code == 429:
        return RateLimitError("openai", f"Rate limited: {text}", status_code)
    return ProviderError("openai", f"HTTP {status_code}: {text}", status_code)


class OpenAIProvider:
    """
    OpenAI-compatible provider — works with OpenAI, Azure OpenAI,
    LM Studio, Ollama (OpenAI mode), and any OpenAI-spec endpoint.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._api_key = api_key or settings.openai_api_key
        self._model = model or settings.openai_model
        self._base_url = (base_url or settings.openai_base_url).rstrip("/")
        self._timeout = timeout or settings.llm_timeout_seconds
        self._chat_url = f"{self._base_url}/chat/completions"

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def _build_body(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool = False,
        json_mode: bool = False,
    ) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.llm_temperature,
            "max_tokens": max_tokens or settings.llm_max_output_tokens,
            "stream": stream,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
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
            resp = await client.post(self._chat_url, headers=self._headers(), json=body)
            if resp.status_code != 200:
                raise _map_status(resp.status_code, resp.text[:300])
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    # ── generate_json ─────────────────────────────────────────────────────────

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        before_sleep=before_sleep_log(logger, "WARNING"),  # type: ignore[arg-type]
        reraise=True,
    )
    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        body = self._build_body(
            prompt, system_prompt, temperature, max_tokens,
            stream=False, json_mode=True,
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._chat_url, headers=self._headers(), json=body)
            if resp.status_code != 200:
                raise _map_status(resp.status_code, resp.text[:300])
            text = resp.json()["choices"][0]["message"]["content"]
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"OpenAIProvider: JSON parse error: {exc}\nRaw: {text}") from exc

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
            async with client.stream("POST", self._chat_url, headers=self._headers(), json=body) as resp:
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
                        chunk = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content")
                    if token:
                        yield token
