"""
core/tracing.py
================
Task 5 — OpenTelemetry instrumentation.

Instruments: FastAPI, SQLAlchemy, Redis, httpx
Exports to: OTLP gRPC (Jaeger / Grafana Tempo) at OTEL_EXPORTER_OTLP_ENDPOINT

Usage — call setup_tracing(app) inside create_app() in main.py.
One line per integration as required.
"""
from __future__ import annotations

import logging

from core.config import settings
from core.logger import logger


def setup_tracing(app=None) -> None:
    """
    Configure OpenTelemetry SDK and instrument all relevant layers.
    No-ops gracefully if OTEL_ENABLED=false or if packages are missing.
    """
    if not settings.otel_enabled:
        logger.debug("OpenTelemetry disabled (OTEL_ENABLED=false)")
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        # ── Tracer provider ───────────────────────────────────────────────────
        resource = Resource.create(
            {
                "service.name": settings.otel_service_name,
                "service.version": settings.app_version,
                "deployment.environment": settings.environment,
            }
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        logger.info("OTel: TracerProvider configured → {}", settings.otel_exporter_endpoint)

        # ── FastAPI instrumentation ───────────────────────────────────────────
        if app is not None:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app)                               # one line
            logger.info("OTel: FastAPI instrumented")

        # ── SQLAlchemy instrumentation ────────────────────────────────────────
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        SQLAlchemyInstrumentor().instrument()                                      # one line
        logger.info("OTel: SQLAlchemy instrumented")

        # ── Redis instrumentation ─────────────────────────────────────────────
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        RedisInstrumentor().instrument()                                           # one line
        logger.info("OTel: Redis instrumented")

        # ── httpx instrumentation ─────────────────────────────────────────────
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        HTTPXClientInstrumentor().instrument()                                     # one line
        logger.info("OTel: httpx instrumented")

        logger.info(
            "OpenTelemetry fully configured | service={} endpoint={}",
            settings.otel_service_name,
            settings.otel_exporter_endpoint,
        )

    except ImportError as exc:
        logger.warning(
            "OpenTelemetry packages not installed — tracing disabled. "
            "Install opentelemetry-sdk and related packages. Error: {}",
            exc,
        )
    except Exception as exc:
        logger.error("OpenTelemetry setup failed: {}", exc)
