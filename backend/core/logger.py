"""
core/logger.py
==============
Structured logger for CoffeeGPT.

Supports two backends:
  - loguru (preferred) — full structured JSON file logging + coloured console
  - stdlib logging (fallback) — used when loguru is not installed

Context binding
---------------
Use  bind_context()  to attach request_id / trace_id / stream_id / event_id
to every log line emitted within a coroutine or request scope:

    log = bind_context(request_id="req-123", trace_id="tr-abc", stream_id="futures")
    log.info("Tick processed | price={}", 226.4)

The bound fields appear in every subsequent log call on that logger instance,
and are serialised to JSON in the log file for easy aggregation.

When loguru is unavailable the fallback uses logging.LoggerAdapter with extra dict.
"""
from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime
from typing import Any

try:
    from loguru import logger as _loguru_logger
    HAS_LOGURU = True
except ModuleNotFoundError:
    HAS_LOGURU = False


# ─── Fallback logger when loguru is absent ────────────────────────────────────

class _StructuredAdapter(logging.LoggerAdapter):
    """
    Wraps stdlib Logger with an extras dict (request_id, trace_id, etc.)
    and a loguru-compatible API: .info("msg {}", arg).
    """

    def _fmt(self, msg: str, args: tuple) -> str:
        if not args:
            return msg
        try:
            return msg.format(*args)
        except Exception:
            return " ".join([msg, *(str(a) for a in args)])

    def process(self, msg, kwargs):
        extra = dict(self.extra or {})
        kwargs.setdefault("extra", {}).update(extra)
        return msg, kwargs

    # ── loguru-compat API ──────────────────────────────────────────────────────

    def debug(self, msg: str, *args, **kwargs) -> None:           # type: ignore[override]
        super().debug(self._fmt(msg, args), **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:            # type: ignore[override]
        super().info(self._fmt(msg, args), **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:         # type: ignore[override]
        super().warning(self._fmt(msg, args), **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:           # type: ignore[override]
        super().error(self._fmt(msg, args), **kwargs)

    def critical(self, msg: str, *args, **kwargs) -> None:        # type: ignore[override]
        super().critical(self._fmt(msg, args), **kwargs)

    def exception(self, msg: str, *args, **kwargs) -> None:       # type: ignore[override]
        super().exception(self._fmt(msg, args), **kwargs)

    def bind(self, **extras) -> "_StructuredAdapter":
        """Return a new adapter with merged extras (loguru-compat)."""
        merged = {**(self.extra or {}), **extras}
        return _StructuredAdapter(self.logger, merged)

    def remove(self) -> None:
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            handler.close()


class _FallbackLogger:
    """Thin wrapper — creates _StructuredAdapters on demand."""

    def __init__(self) -> None:
        self._base = logging.getLogger("coffeegpt")
        self._base.setLevel(logging.DEBUG)
        self._base.propagate = False
        self._adapter = _StructuredAdapter(self._base, {})

    def bind(self, **extras) -> _StructuredAdapter:
        return _StructuredAdapter(self._base, extras)

    def __getattr__(self, name: str):
        return getattr(self._adapter, name)


# ─── Module-level logger (either loguru or fallback) ─────────────────────────

if HAS_LOGURU:
    logger: Any = _loguru_logger
else:
    logger: Any = _FallbackLogger()  # type: ignore[no-redef]


# ─── Context binding ──────────────────────────────────────────────────────────

def bind_context(
    *,
    request_id: str | None = None,
    trace_id: str | None = None,
    stream_id: str | None = None,
    event_id: str | None = None,
    **extra_fields: Any,
) -> Any:
    """
    Return a contextual logger with the given fields bound to every log line.

    Usage:
        log = bind_context(request_id="req-abc", stream_id="futures")
        log.info("Processing tick | price={}", 226.4)

    With loguru, fields appear in the structured JSON file log.
    With stdlib, fields are in LogRecord.extra dict.

    Args:
        request_id:   HTTP request identifier (from X-Request-ID header).
        trace_id:     Distributed trace identifier (e.g. W3C traceparent).
        stream_id:    Which streaming feed ("futures", "monitor", etc.).
        event_id:     Specific event/tick identifier.
        **extra_fields: Any additional structured fields.
    """
    ctx: dict[str, Any] = {}
    if request_id is not None:
        ctx["request_id"] = request_id
    if trace_id is not None:
        ctx["trace_id"] = trace_id
    if stream_id is not None:
        ctx["stream_id"] = stream_id
    if event_id is not None:
        ctx["event_id"] = event_id
    ctx.update(extra_fields)

    if HAS_LOGURU:
        return logger.bind(**ctx)
    return logger.bind(**ctx)


def generate_request_id() -> str:
    """Generate a short unique request/event identifier."""
    return uuid.uuid4().hex[:12]


# ─── Setup function ───────────────────────────────────────────────────────────

def setup_logger() -> Any:
    from core.config import settings
    settings.ensure_directories()

    if HAS_LOGURU:
        logger.remove()

        console_level = "DEBUG" if settings.debug else settings.log_level
        logger.add(
            sys.stdout,
            level=console_level,
            colorize=True,
            format=(
                "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "
                "<dim>[req={extra[request_id]!s} trace={extra[trace_id]!s}]</dim> | "
                "<level>{message}</level>"
            ),
            filter=lambda r: True,
        )

        # Structured JSON file — includes all extra fields
        logger.add(
            settings.logs_root / "coffeegpt_{time:YYYY-MM-DD}.log",
            level="INFO",
            rotation="1 day",
            retention="30 days",
            compression="gz",
            serialize=True,  # emits JSON with extra fields embedded
        )

        # Patch default extras so format string never KeyErrors
        logger.configure(extra={"request_id": "-", "trace_id": "-", "stream_id": "-", "event_id": "-"})
        return logger

    # ── Stdlib fallback setup ──────────────────────────────────────────────────
    from core.config import settings as _s

    logger.remove()  # type: ignore[attr-defined]
    base = logger._base  # type: ignore[attr-defined]

    _console_level: int = logging.DEBUG if _s.debug else int(
        getattr(logging, _s.log_level.upper(), logging.INFO)
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(_console_level)
    console_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | "
            "[req=%(request_id)s trace=%(trace_id)s stream=%(stream_id)s] | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            defaults={"request_id": "-", "trace_id": "-", "stream_id": "-", "event_id": "-"},
        )
    )
    base.addHandler(console_handler)

    file_handler = logging.FileHandler(
        _s.logs_root / f"coffeegpt_{datetime.now().strftime('%Y-%m-%d')}.log",
        encoding="utf-8",
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s:%(lineno)d | "
            "[req=%(request_id)s trace=%(trace_id)s stream=%(stream_id)s] | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            defaults={"request_id": "-", "trace_id": "-", "stream_id": "-", "event_id": "-"},
        )
    )
    base.addHandler(file_handler)
    return logger
