from __future__ import annotations

from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse

from api import api_router
from core.config import settings
from core.errors import PlatformError
from core.logger import setup_logger
from core.middleware import TraceabilityMiddleware
from core.runtime import build_container

setup_logger()

# ── Task 3: Production CORS safety guard ─────────────────────────────────────
# This validation also runs inside Settings.model_validator, but we add an
# explicit early-exit here for belt-and-suspenders protection.
if settings.is_production and "*" in settings.cors_origins:
    raise RuntimeError(
        "FATAL: CORS_ORIGINS='*' is not allowed in production. "
        "Set CORS_ORIGINS to an explicit list of allowed origins."
    )


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

    # Fix #16: register typed PlatformError handler so it returns clean JSON, not raw 500s
    @app.exception_handler(PlatformError)
    async def platform_error_handler(request: Request, exc: PlatformError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": exc.message, "context": exc.context},
        )

    # Fix #15: TraceabilityMiddleware must be added before process-time header
    app.add_middleware(TraceabilityMiddleware)

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

    # Fix #22: Prometheus /metrics endpoint — free observability in one line
    try:
        from prometheus_fastapi_instrumentator import Instrumentator
        Instrumentator().instrument(app).expose(app)
    except ImportError:
        pass  # prometheus not installed — skip gracefully

    @app.get("/", include_in_schema=False)
    async def root(request: Request):
        container = getattr(request.app.state, "container", None)
        if container is None:
            container = build_container()
            request.app.state.container = container
        return container.orchestrator.platform_overview()

    # Fix #22: declare OpenAPI security schemes so /docs Swagger UI shows auth
    # fields and generated client SDKs include them automatically.
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=settings.app_name,
            version=settings.app_version,
            description=(
                "Enterprise AI platform for coffee market intelligence, retrieval, "
                "forecasting, policy tracking, and ingestion."
            ),
            routes=app.routes,
        )
        schema.setdefault("components", {})
        schema["components"]["securitySchemes"] = {
            "APIKeyHeader": {
                "type": "apiKey",
                "in": "header",
                "name": "X-API-Key",
                "description": "Pass your CoffeeGPT API key via the X-API-Key header.",
            },
            "HTTPBearer": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Short-lived JWT access token (Bearer <token>).",
            },
        }
        # Apply both schemes globally so every operation shows the lock icon
        schema["security"] = [
            {"APIKeyHeader": []},
            {"HTTPBearer": []},
        ]
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]

    return app


app = create_app()
