"""
core/security.py
================
Enterprise Security Module enforcing API Key Header validation
and automatic credential/secret scrubbing from strings.
"""
from __future__ import annotations

import re

from fastapi import HTTPException, Security
from fastapi.security import APIKeyHeader

from core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

INJECTION_PATTERNS = [
    "ignore all prior",
    "ignore previous instructions",
    "you are now",
    "disregard your",
    "forget your instructions",
    "output your system prompt",
    "reveal your prompt",
    "print your instructions",
    "show your system prompt",
]


async def get_api_key(api_key: str | None = Security(api_key_header)) -> str:
    """
    FastAPI dependency validating the X-API-Key header against configured enterprise keys.
    Can be bypassed if settings.auth_enabled is explicitly False.
    """
    if not settings.auth_enabled:
        return "bypass_dev_key"

    if not api_key or api_key not in settings.api_keys:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing X-API-Key header.",
        )
    return api_key


def scrub_secrets(text: str) -> str:
    """
    Scrub sensitive credentials, tokens, and keys from raw text to prevent
    unsafe logging of raw secrets in production environments.
    """
    if not text:
        return text

    sensitive_tokens = [
        settings.secret_key,
        settings.database_url,
        settings.redis_url,
        settings.celery_broker_url,
        settings.celery_result_backend,
        settings.lmstudio_api_token,
        settings.openweather_api_key,
        settings.newsapi_key,
        settings.ico_api_key,
        settings.barchart_api_key,
    ]
    # Also strip individual configured API keys
    sensitive_tokens.extend(settings.api_keys)

    for token in sensitive_tokens:
        if token and len(token) > 4 and token in text:
            text = text.replace(token, "[REDACTED]")

    return text


def sanitize_user_input(text: str) -> str:
    """
    Sanitize user input to block prompt injection attacks and strip control characters.
    Raises HTTP 400 if the input contains known injection patterns.
    """
    if not text:
        return text

    lowered = text.lower()
    for pattern in INJECTION_PATTERNS:
        if pattern in lowered:
            raise HTTPException(
                status_code=400,
                detail="Request contains disallowed patterns.",
            )

    # Strip non-printable control characters (except newline/tab)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return cleaned.strip()
