from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from time import perf_counter

import httpx
import redis

from core.config import settings
from core.database import ping_database
from models.schemas import DependencyStatus, DetailedHealthResponse
from services.lmstudio_client import LMStudioClient


class HealthService:
    def __init__(self, lmstudio_client: LMStudioClient | None = None) -> None:
        self.lmstudio_client = lmstudio_client or LMStudioClient()

    async def collect_health(self) -> DetailedHealthResponse:
        services = await asyncio.gather(
            self._probe_postgres(),
            self._probe_redis(),
            self._probe_qdrant(),
            self._probe_lmstudio(),
        )
        overall_status = "ok" if all(item.status == "ok" for item in services) else "degraded"
        return DetailedHealthResponse(
            status=overall_status,
            timestamp=datetime.now(timezone.utc),
            services=services,
        )

    async def _probe_postgres(self) -> DependencyStatus:
        return await self._timed_probe(
            "postgres",
            lambda: asyncio.to_thread(ping_database),
            settings.database_url.rsplit("@", maxsplit=1)[-1],
        )

    async def _probe_redis(self) -> DependencyStatus:
        async def check():
            def ping():
                client = redis.Redis.from_url(settings.redis_url)
                client.ping()

            await asyncio.to_thread(ping)

        return await self._timed_probe("redis", check, settings.redis_url)

    async def _probe_qdrant(self) -> DependencyStatus:
        start = perf_counter()
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(
                    f"http://{settings.qdrant_host}:{settings.qdrant_port}/collections"
                )
                response.raise_for_status()
                collections = [item["name"] for item in response.json().get("result", {}).get("collections", [])]
            status = "ok" if settings.qdrant_collection in collections else "degraded"
            detail = f"collection={settings.qdrant_collection}"
        except Exception as exc:
            status = "unreachable"
            detail = str(exc)
        latency = round((perf_counter() - start) * 1000, 2)
        return DependencyStatus(name="qdrant", status=status, detail=detail, latency_ms=latency)

    async def _probe_lmstudio(self) -> DependencyStatus:
        start = perf_counter()
        try:
            model_status = await self.lmstudio_client.get_model_status(settings.llm_model)
            status = "ok" if model_status.available else "degraded"
            detail = f"model={settings.llm_model}; loaded={'yes' if model_status.loaded else 'no'}"
        except Exception as exc:
            status = "unreachable"
            detail = str(exc)
        latency = round((perf_counter() - start) * 1000, 2)
        return DependencyStatus(name="lmstudio", status=status, detail=detail, latency_ms=latency)

    async def _timed_probe(self, name: str, probe, success_detail: str) -> DependencyStatus:
        start = perf_counter()
        try:
            await probe()
            status = "ok"
            detail = success_detail
        except Exception as exc:
            status = "unreachable"
            detail = str(exc)
        latency = round((perf_counter() - start) * 1000, 2)
        return DependencyStatus(name=name, status=status, detail=detail, latency_ms=latency)
