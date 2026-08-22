"""Admin routes: login, CSRF token, health check."""
from __future__ import annotations

import datetime as _dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from integrations_manager.app.auth import (
    create_access_token,
    create_csrf_token,
    get_current_user,
    require_admin,
    _hash_password,
)
from integrations_manager.app.config import settings
from integrations_manager.app.models import Integration, AuditLog
from integrations_manager.app.schemas import LoginRequest, LoginResponse, CSRFTokenResponse

router = APIRouter(tags=["admin"])


def _get_db(request: Request):
    return request.app.state.db


# ── Health ──────────────────────────────────────────────────────────────

@router.get("/health")
async def health():
    """Health check — never exposes secrets."""
    return {"status": "healthy", "version": settings.APP_VERSION}


# ── Login ───────────────────────────────────────────────────────────────

@router.post("/api/auth/login", response_model=LoginResponse)
async def login(request: Request, body: LoginRequest):
    """Authenticate admin and return JWT + CSRF token."""
    expected_hash = _hash_password(settings.ADMIN_PASSWORD)
    provided_hash = _hash_password(body.password)

    if body.username != settings.ADMIN_USERNAME or not (
        __import__("hmac").compare_digest(expected_hash, provided_hash)
    ):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token(body.username)
    csrf = create_csrf_token()

    # Audit log
    db = _get_db(request)
    db.add(AuditLog(action="login", actor=body.username, details="Successful login"))
    db.commit()

    return LoginResponse(access_token=token, csrf_token=csrf)


# ── CSRF token ──────────────────────────────────────────────────────────

@router.get("/api/auth/csrf", response_model=CSRFTokenResponse)
async def get_csrf_token(user: Annotated[str, Depends(get_current_user)] = ""):
    """Get a fresh CSRF token for state-changing requests."""
    return CSRFTokenResponse(csrf_token=create_csrf_token())


# ── Audit logs (global) ────────────────────────────────────────────────

@router.get("/api/audit")
async def global_audit_logs(
    request: Request,
    limit: int = 100,
    user: Annotated[str, Depends(require_admin)] = "",
):
    """Get global audit logs across all integrations."""
    db = _get_db(request)
    logs = (
        db.query(AuditLog)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": log.id,
            "action": log.action,
            "actor": log.actor,
            "details": log.details,
            "ip_address": log.ip_address,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]
