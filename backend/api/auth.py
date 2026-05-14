"""
api/auth.py
===========
Task 3 — JWT auth endpoints.

Routes:
  POST /auth/token    — exchange a valid API key for access + refresh JWT
  POST /auth/refresh  — exchange a refresh token for a new access token
  GET  /auth/me       — return current user info from access token

Refresh tokens are stored in Redis with TTL matching the token expiry
to enable server-side invalidation (logout / revocation).
"""
from __future__ import annotations

from datetime import timedelta

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from core.config import settings
from core.logger import logger
from core.rate_limit import endpoint_rate_limiter
from core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_auth_rate_limit = endpoint_rate_limiter("auth")
_bearer = HTTPBearer(auto_error=False)

# Redis key prefix for refresh token whitelist
_REFRESH_KEY_PREFIX = "coffee:auth:refresh:"


# ── Schemas ───────────────────────────────────────────────────────────────────

class TokenRequest(BaseModel):
    api_key: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = settings.access_token_expire_minutes * 60


class RefreshRequest(BaseModel):
    refresh_token: str


class UserInfo(BaseModel):
    subject: str
    token_type: str = "access"


# ── Redis helper (lazy) ───────────────────────────────────────────────────────

_redis: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis | None:
    global _redis
    if _redis is not None:
        return _redis
    try:
        _redis = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
        )
        await _redis.ping()
        return _redis
    except Exception as exc:
        logger.warning("Auth: Redis unavailable for refresh token store: {}", exc)
        return None


async def _store_refresh_token(subject: str, token: str) -> None:
    client = await _get_redis()
    if client:
        key = f"{_REFRESH_KEY_PREFIX}{subject}:{token[:16]}"
        ttl = settings.refresh_token_expire_days * 86400
        await client.setex(key, ttl, token)


async def _validate_refresh_token_in_redis(subject: str, token: str) -> bool:
    """Return False if token has been revoked (not in Redis)."""
    client = await _get_redis()
    if client is None:
        return True  # Fail-open when Redis is down
    key = f"{_REFRESH_KEY_PREFIX}{subject}:{token[:16]}"
    stored = await client.get(key)
    return stored == token


async def _revoke_refresh_token(subject: str, token: str) -> None:
    client = await _get_redis()
    if client:
        key = f"{_REFRESH_KEY_PREFIX}{subject}:{token[:16]}"
        await client.delete(key)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/token", response_model=TokenResponse)
async def issue_token(
    body: TokenRequest,
    request: Request,
    _rate: bool = Depends(_auth_rate_limit),
) -> TokenResponse:
    """
    Exchange a valid API key for short-lived access + long-lived refresh JWT.
    The refresh token is persisted in Redis for server-side revocation support.
    """
    if not settings.auth_enabled:
        # In dev mode: accept any non-empty string as a test key
        subject = f"dev:{body.api_key[:8]}"
    else:
        if body.api_key not in settings.api_keys:
            logger.warning("Auth: invalid API key attempt from {}", getattr(request.client, "host", "?"))
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key.",
            )
        subject = f"key:{body.api_key[:8]}...{body.api_key[-4:]}"

    access  = create_access_token(subject)
    refresh = create_refresh_token(subject)

    await _store_refresh_token(subject, refresh)

    logger.info("Auth: token issued for subject={!r}", subject)
    return TokenResponse(access_token=access, refresh_token=refresh)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    body: RefreshRequest,
    _rate: bool = Depends(_auth_rate_limit),
) -> TokenResponse:
    """
    Exchange a valid, non-revoked refresh token for a new access + refresh token pair.
    The old refresh token is revoked (rotation) to prevent replay attacks.
    """
    payload = decode_token(body.refresh_token, expected_type="refresh")
    subject = payload["sub"]

    # Check Redis whitelist
    if not await _validate_refresh_token_in_redis(subject, body.refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked.",
        )

    # Rotate: revoke old, issue new
    await _revoke_refresh_token(subject, body.refresh_token)
    new_access  = create_access_token(subject)
    new_refresh = create_refresh_token(subject)
    await _store_refresh_token(subject, new_refresh)

    logger.info("Auth: token rotated for subject={!r}", subject)
    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.get("/me", response_model=UserInfo)
async def get_me(current_user: str = Depends(get_current_user)) -> UserInfo:
    """Return information about the current authenticated user."""
    return UserInfo(subject=current_user)
