"""
core/security.py
================
Task 3 — Hardened auth + JWT support.

Changes vs original:
  1. Dev bypass (auth_enabled=False) is IP-locked to 127.0.0.1 / localhost ONLY.
     External IPs receive 401 even in dev mode — prevents accidental exposure.
  2. JWT support: short-lived access tokens (15 min) + refresh tokens (7 days)
     stored in Redis. Validation via python-jose.
  3. Prompt injection sanitizer retained and hardened.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from core.config import settings

# ── Scheme objects ────────────────────────────────────────────────────────────
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme  = HTTPBearer(auto_error=False)

# ── Password hashing (for future user management) ────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ── Prompt injection deny-list ────────────────────────────────────────────────
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
    "act as",
    "pretend you are",
    "jailbreak",
    "dan mode",
]

# ── Localhost check ────────────────────────────────────────────────────────────
_LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def _is_local_request(request: Request) -> bool:
    """Return True only if the request originates from localhost."""
    host = getattr(request.client, "host", None) or ""
    return host in _LOCAL_HOSTS


# ── API Key auth ──────────────────────────────────────────────────────────────

async def get_api_key(
    request: Request,
    api_key: str | None = Security(api_key_header),
) -> str:
    """
    Validate X-API-Key header.

    Dev bypass (auth_enabled=False):
      - Allowed ONLY from 127.0.0.1 / ::1 / localhost
      - External callers receive 401 even in dev mode
    """
    if not settings.auth_enabled:
        if _is_local_request(request):
            return "bypass_dev_key"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Dev bypass is restricted to localhost. Set AUTH_ENABLED=true for external access.",
        )

    if not api_key or api_key not in settings.api_keys:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header.",
        )
    return api_key


# ── JWT helpers ───────────────────────────────────────────────────────────────

def _encode_token(data: dict, expires_delta: timedelta) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + expires_delta
    payload["iat"] = datetime.now(timezone.utc)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(subject: str, extra: dict | None = None) -> str:
    """Create a short-lived access JWT (15 min default)."""
    data = {"sub": subject, "type": "access", **(extra or {})}
    return _encode_token(data, timedelta(minutes=settings.access_token_expire_minutes))


def create_refresh_token(subject: str) -> str:
    """Create a long-lived refresh JWT (7 days default)."""
    data = {"sub": subject, "type": "refresh"}
    return _encode_token(data, timedelta(days=settings.refresh_token_expire_days))


def decode_token(token: str, expected_type: str = "access") -> dict:
    """
    Decode and validate a JWT.
    Raises HTTPException 401 on any validation failure.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key,
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != expected_type:
            raise credentials_exception
        if payload.get("sub") is None:
            raise credentials_exception
        return payload
    except JWTError:
        raise credentials_exception


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    """
    FastAPI dependency — validates Bearer JWT and returns the subject (user/key id).
    Use this dependency on endpoints that require full JWT auth.
    """
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(credentials.credentials, expected_type="access")
    return payload["sub"]


# ── Secret scrubbing ──────────────────────────────────────────────────────────

def scrub_secrets(text: str) -> str:
    """
    Scrub sensitive credentials, tokens, and keys from raw text to prevent
    unsafe logging of raw secrets in production environments.
    """
    if not text:
        return text

    sensitive_tokens = [
        settings.secret_key,
        settings.jwt_secret_key,
        settings.database_url,
        settings.redis_url,
        settings.celery_broker_url,
        settings.celery_result_backend,
        settings.lmstudio_api_token,
        settings.openweather_api_key,
        settings.newsapi_key,
        settings.ico_api_key,
        settings.barchart_api_key,
        settings.anthropic_api_key,
        settings.openai_api_key,
    ]
    sensitive_tokens.extend(settings.api_keys)

    for token in sensitive_tokens:
        if token and len(token) > 4 and token in text:
            text = text.replace(token, "[REDACTED]")

    return text


# ── Input sanitizer ───────────────────────────────────────────────────────────

def sanitize_user_input(text: str) -> str:
    """
    Sanitize user input against prompt injection and control characters.
    Raises HTTP 400 on detected injection patterns.
    """
    if not text:
        return text

    lowered = text.lower()
    for pattern in INJECTION_PATTERNS:
        if pattern in lowered:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Request contains disallowed patterns.",
            )

    # Strip non-printable control characters (preserve newline / tab)
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    return cleaned.strip()


# ── Password utilities ────────────────────────────────────────────────────────

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)
