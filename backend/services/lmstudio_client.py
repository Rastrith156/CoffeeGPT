from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from core.config import settings


@dataclass(slots=True)
class LMStudioChatResult:
    text: str
    response_id: str | None
    model_instance_id: str | None
    stats: dict | None = None


@dataclass(slots=True)
class LMStudioModelStatus:
    available: bool
    loaded: bool
    available_model_keys: list[str]


class LMStudioClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_token: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.base_url = self._normalize_base_url(base_url or settings.lmstudio_base_url)
        self.api_token = api_token if api_token is not None else settings.lmstudio_api_token
        self.timeout_seconds = timeout_seconds or settings.llm_timeout_seconds
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            headers=self._headers(),
        )

    def _normalize_base_url(self, base_url: str) -> str:
        normalized = base_url.rstrip("/")
        for suffix in ("/api/v1", "/v1"):
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                break
        return normalized

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_models(self) -> list[dict]:
        response = await self._client.get("/v1/models")
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, list):
            models = payload
        elif isinstance(payload, dict):
            models = payload.get("data") or payload.get("models") or []
        else:
            models = []
        return [item for item in models if isinstance(item, dict)]

    async def get_model_status(self, model_name: str) -> LMStudioModelStatus:
        normalized_target = model_name.strip().lower()
        available_model_keys: list[str] = []
        available = False
        loaded = False

        for item in await self.list_models():
            matched_item = False
            for name in self._candidate_names(item):
                if name not in available_model_keys:
                    available_model_keys.append(name)
                if name.lower() == normalized_target:
                    available = True
                    matched_item = True

            for instance in item.get("loaded_instances", []):
                instance_id = str(instance.get("id", "")).strip()
                if not instance_id:
                    continue
                if instance_id not in available_model_keys:
                    available_model_keys.append(instance_id)
                if instance_id.lower() == normalized_target:
                    available = True
                    loaded = True

            if matched_item:
                loaded_state = self._extract_loaded_state(item)
                loaded = loaded or (loaded_state if loaded_state is not None else True)

        return LMStudioModelStatus(
            available=available,
            loaded=loaded,
            available_model_keys=available_model_keys,
        )

    async def chat(
        self,
        *,
        model: str,
        user_input: str,
        system_prompt: str | None = None,
        previous_response_id: str | None = None,
        store: bool = True,
    ) -> LMStudioChatResult:
        _ = previous_response_id
        _ = store
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_input})

        payload = {
            "model": model,
            "messages": messages,
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_output_tokens,
            "stream": False,
        }

        response = await self._client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        text = ""
        choices = data.get("choices", [])
        if choices and isinstance(choices, list):
            message = choices[0].get("message", {})
            text = self._coerce_text(message.get("content", ""))

        if not text and "output" in data:
            text = self._extract_message_text(data.get("output", []))

        if not text:
            raise ValueError("LM Studio returned no textual message output")

        return LMStudioChatResult(
            text=text,
            response_id=data.get("id") or data.get("response_id"),
            model_instance_id=data.get("model") or data.get("model_instance_id"),
            stats=data.get("usage") or data.get("stats"),
        )

    def _candidate_names(self, model_payload: dict) -> list[str]:
        candidates = [
            str(model_payload.get("key", "")).strip(),
            str(model_payload.get("id", "")).strip(),
            str(model_payload.get("model", "")).strip(),
            str(model_payload.get("display_name", "")).strip(),
            str(model_payload.get("slug", "")).strip(),
        ]
        return [item for item in candidates if item]

    def _extract_loaded_state(self, model_payload: dict[str, Any]) -> bool | None:
        for key in ("loaded", "is_loaded", "ready", "active"):
            value = model_payload.get(key)
            if isinstance(value, bool):
                return value

        state = str(model_payload.get("state") or model_payload.get("status") or "").strip().lower()
        if state in {"loaded", "ready", "running", "active"}:
            return True
        if state in {"error", "failed", "inactive", "unloaded"}:
            return False
        return None

    def _coerce_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = [self._coerce_text(item) for item in content]
            return "\n".join(part for part in parts if part).strip()
        if isinstance(content, dict):
            for key in ("text", "content"):
                value = content.get(key)
                text = self._coerce_text(value)
                if text:
                    return text
        return str(content).strip() if content is not None else ""

    def _extract_message_text(self, output_items: list[dict]) -> str:
        messages = [
            str(item.get("content", "")).strip()
            for item in output_items
            if item.get("type") == "message" and str(item.get("content", "")).strip()
        ]
        if messages:
            return "\n\n".join(messages)

        reasoning = [
            str(item.get("content", "")).strip()
            for item in output_items
            if item.get("type") == "reasoning" and str(item.get("content", "")).strip()
        ]
        if reasoning:
            return "\n\n".join(reasoning)

        raise ValueError("LM Studio returned no textual message output")
