from __future__ import annotations

from dataclasses import dataclass

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
        self.base_url = (base_url or settings.lmstudio_base_url).rstrip("/")
        self.api_token = api_token if api_token is not None else settings.lmstudio_api_token
        self.timeout_seconds = timeout_seconds or settings.llm_timeout_seconds
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
            headers=self._headers(),
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        return headers

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_models(self) -> list[dict]:
        response = await self._client.get("/api/v1/models")
        response.raise_for_status()
        payload = response.json()
        models = payload.get("models") or payload.get("data") or []
        return [item for item in models if isinstance(item, dict)]

    async def get_model_status(self, model_name: str) -> LMStudioModelStatus:
        normalized_target = model_name.strip().lower()
        available_model_keys: list[str] = []
        available = False
        loaded = False

        for item in await self.list_models():
            for name in self._candidate_names(item):
                if name not in available_model_keys:
                    available_model_keys.append(name)
                if name.lower() == normalized_target:
                    available = True

            for instance in item.get("loaded_instances", []):
                instance_id = str(instance.get("id", "")).strip()
                if not instance_id:
                    continue
                if instance_id not in available_model_keys:
                    available_model_keys.append(instance_id)
                if instance_id.lower() == normalized_target:
                    available = True
                    loaded = True

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
        payload = {
            "model": model,
            "input": user_input,
            "system_prompt": system_prompt,
            "temperature": settings.llm_temperature,
            "max_output_tokens": settings.llm_max_output_tokens,
            "context_length": settings.llm_context_length,
            "store": store,
        }
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        payload = {key: value for key, value in payload.items() if value is not None}

        response = await self._client.post("/api/v1/chat", json=payload)
        response.raise_for_status()
        data = response.json()
        return LMStudioChatResult(
            text=self._extract_message_text(data.get("output", [])),
            response_id=data.get("response_id"),
            model_instance_id=data.get("model_instance_id"),
            stats=data.get("stats"),
        )

    def _candidate_names(self, model_payload: dict) -> list[str]:
        candidates = [
            str(model_payload.get("key", "")).strip(),
            str(model_payload.get("id", "")).strip(),
            str(model_payload.get("model", "")).strip(),
            str(model_payload.get("display_name", "")).strip(),
        ]
        return [item for item in candidates if item]

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
