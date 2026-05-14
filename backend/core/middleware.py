"""
core/middleware.py
==================
Enterprise Traceability Middleware. Generates unique Request IDs and Trace IDs,
propagates them via ContextVars, and injects them into downstream HTTP responses.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from core.config import settings

# Thread-safe async context variables holding request-scoped tracing metadata
_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")
_trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")


def get_request_id() -> str:
    """Retrieve the Request ID associated with the current asynchronous execution context."""
    return _request_id_ctx.get()


def get_trace_id() -> str:
    """Retrieve the Trace ID associated with the current asynchronous execution context."""
    return _trace_id_ctx.get()


class TraceabilityMiddleware(BaseHTTPMiddleware):
    """
    ASGI Middleware establishing request lifecycle tracing. Intercepts incoming requests,
    extracts or initializes distributed trace identifiers, and injects response tracking headers.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Generate or extract unique trace boundaries
        req_id = f"req_{uuid.uuid4().hex[:12]}"
        trace_id = request.headers.get(settings.trace_header_name) or f"trace_{uuid.uuid4().hex[:16]}"

        # Bind tracing tags to the active ContextVar context
        req_token = _request_id_ctx.set(req_id)
        trace_token = _trace_id_ctx.set(trace_id)

        try:
            response: Response = await call_next(request)
            # Expose trace identifiers to external client consumers
            response.headers["X-Request-ID"] = req_id
            response.headers[settings.trace_header_name] = trace_id
            return response
        finally:
            # Restore ContextVar scope cleanly
            _request_id_ctx.reset(req_token)
            _trace_id_ctx.reset(trace_token)
