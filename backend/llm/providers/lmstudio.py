"""
llm/providers/lmstudio.py
=========================
LM Studio / OpenAI-compatible local API provider.

Updated for Task 2: implements stream_generate() using SSE token streaming
against the OpenAI-spec /v1/chat/completions endpoint.
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
from llm.providers.base import ProviderError

_RETRYABLE = (httpx.TimeoutException, httpx.NetworkError, ProviderError)


class LMStudioProvider:
    """
    Adapter for LM Studio or any OpenAI-compatible local API.
    Implements LLMProviderProtocol (duck-typed).
    """

    def __init__(self, client=None) -> None:
        # Allow injecting existing LMStudioClient for backwards compat
        self._legacy_client = client
        self._base_url = settings.lmstudio_base_url.rstrip("/")
        self._chat_url = f"{self._base_url}/v1/chat/completions"
        self._model = settings.llm_model
        self._timeout = settings.llm_timeout_seconds

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if settings.lmstudio_api_token:
            h["Authorization"] = f"Bearer {settings.lmstudio_api_token}"
        return h

    def _build_body(
        self,
        prompt: str,
        system_prompt: str | None,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool = False,
    ) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return {
            "model": self._model,
            "messages": messages,
            "temperature": temperature if temperature is not None else settings.llm_temperature,
            "max_tokens": max_tokens or settings.llm_max_output_tokens,
            "stream": stream,
        }

    # ── Backward-compat: use legacy client when injected ─────────────────────

    async def _legacy_generate(
        self,
        prompt: str,
        system_prompt: str | None,
    ) -> str:
        result = await self._legacy_client.chat(
            model=self._model,
            user_input=prompt,
            system_prompt=system_prompt,
        )
        return result.text

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
        if self._legacy_client is not None:
            return await self._legacy_generate(prompt, system_prompt)

        body = self._build_body(prompt, system_prompt, temperature, max_tokens, stream=False)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(self._chat_url, headers=self._headers(), json=body)
            if resp.status_code != 200:
                raise ProviderError("lmstudio", f"HTTP {resp.status_code}: {resp.text[:300]}", resp.status_code)
            return resp.json()["choices"][0]["message"]["content"]

    # ── generate_json ─────────────────────────────────────────────────────────

    async def generate_json(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        enhanced = prompt if "json" in prompt.lower() else prompt + "\n\nResponse must be a valid JSON object."
        text = await self.generate(enhanced, system_prompt, temperature, max_tokens, **kwargs)
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LMStudioProvider: JSON parse error: {exc}\nRaw: {text}") from exc

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
                    raise ProviderError("lmstudio", f"HTTP {resp.status_code}: {content.decode()[:300]}", resp.status_code)
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
