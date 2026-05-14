"""
llm/providers/ollama.py
=======================
Task 2 — Ollama local model provider via raw httpx.

Ollama exposes an OpenAI-compatible chat endpoint at /api/chat,
plus a native /api/generate.  We use /api/chat for consistency
with the other providers.

Features:
  - generate()        → full completion (stream=false)
  - generate_json()   → JSON-coerced completion (format: "json")
  - stream_generate() → token-by-token NDJSON streaming
  - Tenacity: 3 retries on connection/timeout errors (local, so no rate limits)
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

_RETRYABLE = (httpx.TimeoutException, httpx.NetworkError, ProviderError)


class OllamaProvider:
    """
    Ollama local LLM provider.
    Base URL defaults to http://localhost:11434.
    """

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self._base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._model = model or settings.ollama_model
        self._timeout = timeout or settings.llm_timeout_seconds
        self._chat_url = f"{self._base_url}/api/chat"

    def _build_messages(
        self, prompt: str, system_prompt: str | None
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return messages

    def _build_body(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool = False,
        json_format: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": self._build_messages(prompt, system_prompt),
            "stream": stream,
            "options": {
                "temperature": temperature if temperature is not None else settings.llm_temperature,
                "num_predict": max_tokens or settings.llm_max_output_tokens,
            },
        }
        if json_format:
            body["format"] = "json"
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
            resp = await client.post(self._chat_url, json=body)
            if resp.status_code != 200:
                raise ProviderError("ollama", f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
            data = resp.json()
            return data["message"]["content"]

    # ── generate_json ─────────────────────────────────────────────────────────

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
            stream=False, json_format=True,
        )
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._chat_url, json=body)
            if resp.status_code != 200:
                raise ProviderError("ollama", f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
            text = resp.json()["message"]["content"]
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"OllamaProvider: JSON parse error: {exc}\nRaw: {text}") from exc

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
            async with client.stream("POST", self._chat_url, json=body) as resp:
                if resp.status_code != 200:
                    content = await resp.aread()
                    raise ProviderError("ollama", f"HTTP {resp.status_code}: {content.decode()[:300]}", resp.status_code)
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("done"):
                        break
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        yield token
