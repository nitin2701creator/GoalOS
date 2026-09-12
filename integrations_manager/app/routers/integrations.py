"""API routes for integration management.

GET    /api/integrations                     — list all integrations
GET    /api/integrations/{slug}              — get integration detail
GET    /api/integrations/{slug}/credentials  — get masked credentials
POST   /api/integrations/{slug}/credentials  — save credentials
POST   /api/integrations/{slug}/test         — test connection
POST   /api/integrations/{slug}/connect      — initiate OAuth / save api-key creds
POST   /api/integrations/{slug}/disconnect   — disconnect integration
GET    /api/integrations/{slug}/status       — get connection status
"""
from __future__ import annotations

import datetime as _dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.integrations.http_client import HttpError

from integrations_manager.app.auth import get_current_user, require_csrf
from integrations_manager.app.encryption import CredentialEncryption
from integrations_manager.app.oauth_flow import (
    OAuthExchangeError,
    OAuthNotConfiguredError,
    apply_refreshed_tokens,
    build_authorization_url,
    refresh_access_token,
    supports_refresh,
)
from integrations_manager.app.models import (
    AuditLog,
    ConnectionStatus,
    Credential,
    Integration,
    OAuthToken,
)
from integrations_manager.app.providers import PROVIDER_REGISTRY
from integrations_manager.app.providers.base import BaseProvider
from integrations_manager.app.status import (
    AUTH_REQUIRED,
    CONFIGURED,
    CONNECTED,
    DISABLED,
    EXPIRED,
    NOT_CONFIGURED,
)
from integrations_manager.app.schemas import (
    AuditLogEntry,
    ConnectResponse,
    CredentialField,
    DisconnectResponse,
    IntegrationDetail,
    IntegrationSummary,
    MaskedCredential,
    SaveCredentialsRequest,
    SaveCredentialsResponse,
    TestConnectionResponse,
    AccountInfoResponse,
)

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


def _get_provider(slug: str) -> BaseProvider:
    cls = PROVIDER_REGISTRY.get(slug)
    if not cls:
        raise HTTPException(status_code=404, detail=f"Integration '{slug}' not found")
    return cls()


def _get_db(request: Request):
    return request.app.state.db


def _get_encryption(request: Request) -> CredentialEncryption:
    return request.app.state.encryption


def _get_integration_or_404(db, slug: str) -> Integration:
    integration = db.query(Integration).filter(Integration.slug == slug).first()
    if not integration:
        raise HTTPException(status_code=404, detail=f"Integration '{slug}' not found")
    return integration


def _get_or_create_status(db, integration_id: int) -> ConnectionStatus:
    status = db.query(ConnectionStatus).filter(
        ConnectionStatus.integration_id == integration_id
    ).first()
    if not status:
        status = ConnectionStatus(integration_id=integration_id, status="not_configured")
        db.add(status)
        db.commit()
        db.refresh(status)
    return status


def _log_audit(db, integration_id: int | None, action: str, actor: str, details: str, ip: str = ""):
    log = AuditLog(
        integration_id=integration_id,
        action=action,
        actor=actor,
        details=details,
        ip_address=ip,
    )
    db.add(log)
    db.commit()


def _effective_status(db, integ: Integration, status_row: ConnectionStatus | None) -> str:
    """Derive the canonical connection state for an integration.

    Layers token expiry and the disabled flag on top of the last stored
    status so the API never reports an expired token as healthy.
    """
    if not integ.is_enabled:
        return DISABLED

    stored = status_row.status if status_row and status_row.status else NOT_CONFIGURED

    if integ.auth_type == "oauth2":
        oauth = db.query(OAuthToken).filter(
            OAuthToken.integration_id == integ.id
        ).first()
        if oauth:
            if oauth.expires_at and oauth.expires_at <= _dt.datetime.utcnow():
                return EXPIRED
            return stored if stored != NOT_CONFIGURED else CONFIGURED

        has_creds = db.query(Credential).filter(
            Credential.integration_id == integ.id
        ).first() is not None
        if has_creds:
            return stored if stored != NOT_CONFIGURED else CONFIGURED
        if stored in (NOT_CONFIGURED, AUTH_REQUIRED):
            return AUTH_REQUIRED
        return stored

    return stored


# ── List all integrations ───────────────────────────────────────────────

@router.get("", response_model=list[IntegrationSummary])
async def list_integrations(
    request: Request,
    _user: Annotated[str, Depends(get_current_user)] = "",
):
    db = _get_db(request)
    integrations = db.query(Integration).order_by(Integration.id).all()
    result = []
    for integ in integrations:
        status = _get_or_create_status(db, integ.id)
        result.append(IntegrationSummary(
            id=integ.id,
            slug=integ.slug,
            name=integ.name,
            description=integ.description,
            icon=integ.icon,
            auth_type=integ.auth_type,
            status=_effective_status(db, integ, status),
            last_connected_at=status.last_connected_at,
            error_message=status.error_message,
            is_enabled=integ.is_enabled,
        ))
    return result


# ── Get integration detail ──────────────────────────────────────────────

@router.get("/{slug}", response_model=IntegrationDetail)
async def get_integration(
    slug: str,
    request: Request,
    _user: Annotated[str, Depends(get_current_user)] = "",
):
    db = _get_db(request)
    integ = _get_integration_or_404(db, slug)
    status = _get_or_create_status(db, integ.id)
    provider = _get_provider(slug)

    # Check if credentials exist
    has_creds = db.query(Credential).filter(
        Credential.integration_id == integ.id
    ).first() is not None

    has_oauth = db.query(OAuthToken).filter(
        OAuthToken.integration_id == integ.id
    ).first() is not None

    return IntegrationDetail(
        id=integ.id,
        slug=integ.slug,
        name=integ.name,
        description=integ.description,
        icon=integ.icon,
        auth_type=integ.auth_type,
        status=_effective_status(db, integ, status),
        last_connected_at=status.last_connected_at,
        error_message=status.error_message,
        credential_fields=provider.get_credential_fields(),
        has_credentials=has_creds,
        has_oauth=has_oauth,
        is_enabled=integ.is_enabled,
    )


# ── Get masked credentials ─────────────────────────────────────────────

@router.get("/{slug}/credentials", response_model=list[MaskedCredential])
async def get_masked_credentials(
    slug: str,
    request: Request,
    _user: Annotated[str, Depends(get_current_user)] = "",
):
    db = _get_db(request)
    integ = _get_integration_or_404(db, slug)
    provider = _get_provider(slug)
    encryption = _get_encryption(request)

    fields = provider.get_credential_fields()
    creds = db.query(Credential).filter(Credential.integration_id == integ.id).all()
    cred_map = {c.credential_key: c for c in creds}

    result = []
    for field_def in fields:
        key = field_def["key"]
        cred = cred_map.get(key)
        if cred:
            try:
                plaintext = encryption.decrypt(cred.encrypted_value)
                masked = provider.mask_value(key, plaintext)
            except Exception:
                masked = "••••••••"
            result.append(MaskedCredential(
                key=key,
                label=field_def["label"],
                masked_value=masked,
                is_set=True,
            ))
        else:
            result.append(MaskedCredential(
                key=key,
                label=field_def["label"],
                masked_value="",
                is_set=False,
            ))
    return result


# ── Save credentials ────────────────────────────────────────────────────

@router.post("/{slug}/credentials", response_model=SaveCredentialsResponse)
async def save_credentials(
    slug: str,
    request: Request,
    body: SaveCredentialsRequest,
    _user: Annotated[str, Depends(get_current_user)] = "",
    _csrf: Annotated[None, Depends(require_csrf)] = None,
):
    db = _get_db(request)
    integ = _get_integration_or_404(db, slug)
    encryption = _get_encryption(request)

    for key, value in body.credentials.items():
        if not value:
            continue
        existing = db.query(Credential).filter(
            Credential.integration_id == integ.id,
            Credential.credential_key == key,
        ).first()
        encrypted = encryption.encrypt(value)
        if existing:
            existing.encrypted_value = encrypted
        else:
            db.add(Credential(
                integration_id=integ.id,
                credential_key=key,
                encrypted_value=encrypted,
            ))

    # Update status
    status = _get_or_create_status(db, integ.id)
    status.status = "configured"

    _log_audit(db, integ.id, "save_credentials", _user, f"Saved credentials for {slug}")

    db.commit()
    return SaveCredentialsResponse(success=True, message="Credentials saved")


# ── Test connection ─────────────────────────────────────────────────────

async def _handle_expired_token(
    db,
    integ: Integration,
    oauth: OAuthToken,
    decrypted: dict[str, str],
    encryption: CredentialEncryption,
    actor: str,
) -> TestConnectionResponse:
    """Attempt a refresh for an expired token, else report it as expired."""
    slug = integ.slug
    provider = _get_provider(slug)
    status = _get_or_create_status(db, integ.id)

    refresh_token = decrypted.get("refresh_token", "")
    if refresh_token and supports_refresh(slug):
        try:
            token_data = refresh_access_token(slug, refresh_token)
            new_access = apply_refreshed_tokens(oauth, encryption, token_data)
        except (OAuthExchangeError, OAuthNotConfiguredError, HttpError):
            status.status = EXPIRED
            status.error_message = "Access token expired — reconnect required"
            _log_audit(db, integ.id, "refresh_failed", actor, f"Refresh failed for {slug}")
            db.commit()
            return TestConnectionResponse(
                success=False,
                message="Access token expired — reconnect required",
                status=EXPIRED,
            )
        decrypted["access_token"] = new_access
        if token_data.get("refresh_token"):
            decrypted["refresh_token"] = token_data["refresh_token"]
        db.commit()

        result = await provider.test_connection(decrypted)
        status_text = (result.status or "").strip() or (
            CONNECTED if result.success else "error"
        )
        status.last_tested_at = _dt.datetime.utcnow()
        if result.success:
            status.status = status_text
            status.last_connected_at = _dt.datetime.utcnow()
            status.error_message = None
        else:
            status.status = status_text
            status.error_message = result.message
        _log_audit(db, integ.id, "test_connection", actor,
                   f"Test {'passed' if result.success else 'failed'} after refresh: {result.message}")
        db.commit()
        return TestConnectionResponse(
            success=result.success,
            message=result.message,
            details=result.details,
            status=status_text,
        )

    status.status = EXPIRED
    status.error_message = "Access token expired — reconnect required"
    _log_audit(db, integ.id, "test_connection", actor,
               "Test failed: access token expired, no refresh available")
    db.commit()
    return TestConnectionResponse(
        success=False,
        message="Access token expired — reconnect required",
        status=EXPIRED,
    )


@router.post("/{slug}/test", response_model=TestConnectionResponse)
async def test_connection(
    slug: str,
    request: Request,
    _user: Annotated[str, Depends(get_current_user)] = "",
    _csrf: Annotated[None, Depends(require_csrf)] = None,
):
    db = _get_db(request)
    integ = _get_integration_or_404(db, slug)
    provider = _get_provider(slug)
    encryption = _get_encryption(request)

    # Gather decrypted credentials
    creds = db.query(Credential).filter(Credential.integration_id == integ.id).all()
    decrypted = {}
    for c in creds:
        try:
            decrypted[c.credential_key] = encryption.decrypt(c.encrypted_value)
        except Exception:
            pass

    # Also include OAuth tokens — refreshing first when the stored token
    # has expired so an expired token is never silently treated as healthy.
    oauth = db.query(OAuthToken).filter(OAuthToken.integration_id == integ.id).first()
    if oauth:
        try:
            decrypted["access_token"] = encryption.decrypt(oauth.encrypted_access_token)
        except Exception:
            pass
        if oauth.encrypted_refresh_token:
            try:
                decrypted["refresh_token"] = encryption.decrypt(oauth.encrypted_refresh_token)
            except Exception:
                pass

        if oauth.expires_at and oauth.expires_at <= _dt.datetime.utcnow():
            return await _handle_expired_token(
                db, integ, oauth, decrypted, encryption, _user
            )

    result = await provider.test_connection(decrypted)

    # Normalize the canonical status reported by the provider so every
    # integration surfaces one of the six UI states.
    status_text = (result.status or "").strip() or (
        "connected" if result.success else "error"
    )

    # Update status
    status = _get_or_create_status(db, integ.id)
    status.last_tested_at = _dt.datetime.utcnow()
    if result.success:
        status.status = status_text
        status.last_connected_at = _dt.datetime.utcnow()
        status.error_message = None
    else:
        status.status = status_text
        status.error_message = result.message

    _log_audit(db, integ.id, "test_connection", _user, f"Test {'passed' if result.success else 'failed'}: {result.message}")
    db.commit()

    return TestConnectionResponse(
        success=result.success,
        message=result.message,
        details=result.details,
        status=status_text,
    )


# ── Connect (OAuth redirect or API-key save) ───────────────────────────

@router.post("/{slug}/connect", response_model=ConnectResponse)
async def connect_integration(
    slug: str,
    request: Request,
    _user: Annotated[str, Depends(get_current_user)] = "",
    _csrf: Annotated[None, Depends(require_csrf)] = None,
):
    db = _get_db(request)
    integ = _get_integration_or_404(db, slug)
    provider = _get_provider(slug)

    oauth_config = provider.get_oauth_config()
    if oauth_config:
        extra_params = {"duration": "permanent"} if slug == "reddit" else None
        try:
            redirect_url = build_authorization_url(
                slug=slug,
                auth_url=oauth_config.auth_url,
                redirect_uri=oauth_config.redirect_uri,
                scopes=oauth_config.scopes,
                db=db,
                encryption=_get_encryption(request),
                extra_params=extra_params,
            )
        except OAuthNotConfiguredError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return ConnectResponse(
            success=True,
            message="Redirecting to OAuth authorization",
            redirect_url=redirect_url,
        )

    return ConnectResponse(
        success=True,
        message="Use POST /credentials to save API key credentials, then test connection",
    )


# ── Disconnect ──────────────────────────────────────────────────────────

@router.post("/{slug}/disconnect", response_model=DisconnectResponse)
async def disconnect_integration(
    slug: str,
    request: Request,
    _user: Annotated[str, Depends(get_current_user)] = "",
    _csrf: Annotated[None, Depends(require_csrf)] = None,
):
    db = _get_db(request)
    integ = _get_integration_or_404(db, slug)

    # Remove credentials and OAuth tokens
    db.query(Credential).filter(Credential.integration_id == integ.id).delete()
    db.query(OAuthToken).filter(OAuthToken.integration_id == integ.id).delete()

    # Reset status
    status = _get_or_create_status(db, integ.id)
    status.status = "not_configured"
    status.last_connected_at = None
    status.error_message = None

    _log_audit(db, integ.id, "disconnect", _user, f"Disconnected {slug}")
    db.commit()

    return DisconnectResponse(success=True, message=f"Disconnected {slug}")


# ── Get status ──────────────────────────────────────────────────────────

@router.get("/{slug}/status")
async def get_status(
    slug: str,
    request: Request,
    _user: Annotated[str, Depends(get_current_user)] = "",
):
    db = _get_db(request)
    integ = _get_integration_or_404(db, slug)
    status = _get_or_create_status(db, integ.id)
    return {
        "slug": slug,
        "status": _effective_status(db, integ, status),
        "last_connected_at": status.last_connected_at.isoformat() if status.last_connected_at else None,
        "last_tested_at": status.last_tested_at.isoformat() if status.last_tested_at else None,
        "error_message": status.error_message,
        "is_enabled": integ.is_enabled,
    }


# ── Audit logs ──────────────────────────────────────────────────────────

@router.get("/{slug}/audit", response_model=list[AuditLogEntry])
async def get_audit_logs(
    slug: str,
    request: Request,
    limit: int = 50,
    _user: Annotated[str, Depends(get_current_user)] = "",
):
    db = _get_db(request)
    integ = _get_integration_or_404(db, slug)
    logs = (
        db.query(AuditLog)
        .filter(AuditLog.integration_id == integ.id)
        .order_by(AuditLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        AuditLogEntry(
            id=log.id,
            integration_slug=slug,
            action=log.action,
            actor=log.actor,
            details=log.details,
            created_at=log.created_at,
        )
        for log in logs
    ]
