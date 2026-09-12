"""OAuth callback and token-refresh routes for all providers.

These routes handle the OAuth redirect callback, exchange code for tokens,
store encrypted tokens in the database, and refresh expired access tokens.

The callback requires a ``state`` that was persisted by the ``connect``
route; it is validated (provider match + not expired) and consumed exactly
once before any token is exchanged.
"""
from __future__ import annotations

import datetime as _dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.integrations.http_client import HttpError

from integrations_manager.app.auth import get_current_user, require_csrf
from integrations_manager.app.models import AuditLog, ConnectionStatus, Integration, OAuthToken, OAuthState
from integrations_manager.app.oauth_flow import (
    OAuthExchangeError,
    OAuthNotConfiguredError,
    apply_refreshed_tokens,
    exchange_code,
    refresh_access_token,
)
from integrations_manager.app.providers import PROVIDER_REGISTRY
from integrations_manager.app.schemas import TokenRefreshResponse
from integrations_manager.app.status import CONNECTED, EXPIRED

router = APIRouter(prefix="/api/oauth", tags=["oauth"])


def _get_db(request: Request):
    return request.app.state.db


def _get_encryption(request: Request):
    return request.app.state.encryption


def _integration_or_404(db, provider: str) -> Integration:
    integration = db.query(Integration).filter(Integration.slug == provider).first()
    if not integration:
        raise HTTPException(status_code=404, detail=f"Integration '{provider}' not found")
    return integration


def _status_row(db, integration: Integration) -> ConnectionStatus:
    status = db.query(ConnectionStatus).filter(
        ConnectionStatus.integration_id == integration.id
    ).first()
    if not status:
        status = ConnectionStatus(integration_id=integration.id, status="not_configured")
        db.add(status)
    return status


async def _require_pending_state(db, encryption, provider: str, state: str | None):
    """Validate and consume the persisted OAuth state, returning its secrets.

    The state must exist, belong to ``provider``, not be expired, and not
    already be consumed (one-time use). The row is marked consumed before
    the caller performs the token exchange so a replayed callback fails.
    """
    if not state:
        raise HTTPException(status_code=400, detail="Missing OAuth state")

    oauth_state = db.query(OAuthState).filter(OAuthState.state == state).first()
    if oauth_state is None or oauth_state.consumed_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if oauth_state.expires_at < _dt.datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
    if oauth_state.provider != provider:
        raise HTTPException(status_code=400, detail="State mismatch")

    code_verifier = None
    if oauth_state.encrypted_code_verifier:
        try:
            code_verifier = encryption.decrypt(oauth_state.encrypted_code_verifier)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")

    redirect_uri = oauth_state.redirect_uri

    # One-time use: consume before exchanging the code.
    oauth_state.consumed_at = _dt.datetime.utcnow()

    return code_verifier, redirect_uri


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: str = Query(...),
    state: str | None = Query(None),
    error: str | None = Query(None),
):
    """Handle the OAuth redirect callback from any provider."""
    db = _get_db(request)
    encryption = _get_encryption(request)

    if error:
        raise HTTPException(status_code=400, detail="Authorization failed by provider")

    code_verifier, redirect_uri = await _require_pending_state(db, encryption, provider, state)
    integration = _integration_or_404(db, provider)

    # Exchange code for tokens using the exact redirect URI and PKCE
    # verifier the authorization URL was built with.
    try:
        token_data = exchange_code(provider, code, redirect_uri, code_verifier)
    except OAuthNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HttpError as exc:
        raise HTTPException(status_code=400, detail="Token exchange failed")
    except OAuthExchangeError as exc:
        raise HTTPException(status_code=400, detail="Token exchange failed")

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)
    token_type = token_data.get("token_type", "Bearer")
    scope = token_data.get("scope", "")

    if not access_token:
        raise HTTPException(status_code=400, detail="No access_token in response")

    # Encrypt and store tokens
    existing = db.query(OAuthToken).filter(
        OAuthToken.integration_id == integration.id,
        OAuthToken.provider == provider,
    ).first()

    enc_access = encryption.encrypt(access_token)
    enc_refresh = encryption.encrypt(refresh_token) if refresh_token else None
    try:
        expires_in_seconds = int(expires_in)
    except (TypeError, ValueError):
        expires_in_seconds = 3600
    expires_at = _dt.datetime.utcnow() + _dt.timedelta(seconds=expires_in_seconds)

    if existing:
        existing.encrypted_access_token = enc_access
        if enc_refresh:
            existing.encrypted_refresh_token = enc_refresh
        existing.expires_at = expires_at
        existing.scopes = scope
    else:
        db.add(OAuthToken(
            integration_id=integration.id,
            provider=provider,
            encrypted_access_token=enc_access,
            encrypted_refresh_token=enc_refresh,
            token_type=token_type,
            expires_at=expires_at,
            scopes=scope,
        ))

    # Update connection status
    status = _status_row(db, integration)
    status.status = CONNECTED
    status.last_connected_at = _dt.datetime.utcnow()
    status.error_message = None

    db.commit()

    # Return success HTML
    return HTMLResponse(f"""
    <html><head><title>Connected</title></head>
    <body style="font-family:sans-serif;text-align:center;padding:60px">
        <h1>✅ {provider.replace('_',' ').title()} Connected</h1>
        <p>You can close this window and return to the dashboard.</p>
        <script>setTimeout(() => window.close(), 3000);</script>
    </body></html>
    """)


@router.post("/{provider}/refresh", response_model=TokenRefreshResponse)
async def refresh_tokens_endpoint(
    provider: str,
    request: Request,
    _user: Annotated[str, Depends(get_current_user)] = "",
    _csrf: Annotated[None, Depends(require_csrf)] = None,
):
    """Refresh an expired access token from the stored refresh token.

    On success the new tokens are persisted and the connection status is
    set to ``connected``. On failure the status is set to ``expired`` so
    the UI never reports a stale token as healthy.
    """
    db = _get_db(request)
    encryption = _get_encryption(request)

    integration = _integration_or_404(db, provider)
    oauth = db.query(OAuthToken).filter(
        OAuthToken.integration_id == integration.id,
        OAuthToken.provider == provider,
    ).first()
    if not oauth or not oauth.encrypted_refresh_token:
        raise HTTPException(status_code=409, detail="No refresh token stored — re-authorize")

    refresh_token = encryption.decrypt(oauth.encrypted_refresh_token)
    try:
        token_data = refresh_access_token(provider, refresh_token)
        apply_refreshed_tokens(oauth, encryption, token_data)
    except OAuthNotConfiguredError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OAuthExchangeError:
        status = _status_row(db, integration)
        status.status = EXPIRED
        status.error_message = "Access token refresh failed — reconnect required"
        db.commit()
        raise HTTPException(status_code=400, detail="Token refresh failed — reconnect required")
    except HttpError:
        status = _status_row(db, integration)
        status.status = EXPIRED
        status.error_message = "Access token refresh failed — reconnect required"
        db.commit()
        raise HTTPException(status_code=400, detail="Token refresh failed — reconnect required")

    status = _status_row(db, integration)
    status.status = CONNECTED
    status.last_connected_at = _dt.datetime.utcnow()
    status.error_message = None
    db.add(AuditLog(
        integration_id=integration.id,
        action="refresh_token",
        actor=_user,
        details=f"Refreshed access token for {provider}",
    ))
    db.commit()

    return TokenRefreshResponse(success=True, message="Access token refreshed")