"""Admin authentication: JWT tokens, rate limiting, CSRF protection.

Security requirements:
- JWT for session management
- Rate limiting on login endpoint
- CSRF token in headers
- No credentials in logs
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import secrets
from typing import Annotated

import jwt
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from integrations_manager.app.config import settings

# ── Password hashing (simple SHA-256 salted for admin, not bcrypt — admin-only) ──

_SALT = "goalos-integrations-manager-v1"


def _hash_password(password: str) -> str:
    """Hash password with salt."""
    return hashlib.sha256(f"{_SALT}:{password}".encode()).hexdigest()


# ── CSRF protection ──────────────────────────────────────────────────────

_csrf_tokens: dict[str, _dt.datetime] = {}  # token -> expiry
_CSRF_TTL = _dt.timedelta(minutes=30)


def create_csrf_token() -> str:
    token = secrets.token_urlsafe(32)
    _csrf_tokens[token] = _dt.datetime.utcnow() + _CSRF_TTL
    return token


def validate_csrf_token(token: str | None) -> bool:
    if not token:
        return False
    expiry = _csrf_tokens.pop(token, None)
    if expiry is None:
        return False
    return _dt.datetime.utcnow() < expiry


# ── JWT ──────────────────────────────────────────────────────────────────

bearer_scheme = HTTPBearer(auto_error=False)


def create_access_token(username: str) -> str:
    payload = {
        "sub": username,
        "iat": _dt.datetime.utcnow(),
        "exp": _dt.datetime.utcnow() + _dt.timedelta(minutes=settings.JWT_EXPIRY_MINUTES),
        "jti": secrets.token_urlsafe(16),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ── Dependencies ─────────────────────────────────────────────────────────

async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> str:
    """Validate JWT and return username."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(credentials.credentials)
    return payload.get("sub", "admin")


def require_csrf(
    x_csrf_token: Annotated[str | None, Header()] = None,
) -> None:
    """Validate CSRF token on state-changing requests."""
    if not validate_csrf_token(x_csrf_token):
        raise HTTPException(status_code=403, detail="Invalid or missing CSRF token")


async def require_admin(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> str:
    """Combined auth: check JWT or API key header."""
    # Check JWT
    if credentials:
        payload = decode_access_token(credentials.credentials)
        return payload.get("sub", "admin")

    # Check API key (for GoalOS → credentials manager calls)
    api_key = request.headers.get("X-API-Key")
    if api_key:
        expected = settings.ADMIN_PASSWORD  # Simple API key for service-to-service
        if secrets.compare_digest(api_key, expected):
            return "goalos-service"

    raise HTTPException(status_code=401, detail="Not authenticated")
