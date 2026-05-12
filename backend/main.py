from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from api import api_router
from core.config import settings
from core.logger import setup_logger
from core.runtime import build_container

setup_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = build_container()
    app.state.container = container
    await container.startup()
    yield
    await container.shutdown()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Enterprise AI platform for coffee market intelligence, retrieval, "
            "forecasting, policy tracking, and ingestion."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        started_at = perf_counter()
        response = await call_next(request)
        response.headers["X-Process-Time"] = f"{(perf_counter() - started_at) * 1000:.2f}ms"
        return response

    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/", include_in_schema=False)
    async def root(request: Request):
        container = getattr(request.app.state, "container", None)
        if container is None:
            container = build_container()
            request.app.state.container = container
        return container.orchestrator.platform_overview()

    return app


app = create_app()
