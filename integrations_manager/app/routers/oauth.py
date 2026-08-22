"""OAuth callback routes for all providers.

These routes handle the OAuth redirect callback, exchange code for tokens,
and store encrypted tokens in the database.
"""
from __future__ import annotations

import datetime as _dt
import json
from base64 import b64encode
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from integrations_manager.app.auth import get_current_user
from integrations_manager.app.config import settings
from integrations_manager.app.encryption import CredentialEncryption
from integrations_manager.app.models import Integration, OAuthToken, ConnectionStatus
from integrations_manager.app.providers import PROVIDER_REGISTRY

router = APIRouter(prefix="/api/oauth", tags=["oauth"])


def _get_db(request: Request):
    return request.app.state.db


def _get_encryption(request: Request) -> CredentialEncryption:
    return request.app.state.encryption


async def _exchange_code(slug: str, code: str, redirect_uri: str) -> dict:
    """Exchange authorization code for tokens using provider-specific logic."""
    if slug == "google_analytics":
        data = urlencode({
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }).encode()
        req = Request("https://oauth2.googleapis.com/token", data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    elif slug == "meta":
        data = urlencode({
            "code": code,
            "client_id": settings.META_APP_ID,
            "client_secret": settings.META_APP_SECRET,
            "redirect_uri": redirect_uri,
        }).encode()
        req = Request(f"https://graph.facebook.com/v19.0/oauth/access_token?{data.decode()}", method="GET")
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    elif slug == "linkedin":
        auth = b64encode(f"{settings.LINKEDIN_CLIENT_ID}:{settings.LINKEDIN_CLIENT_SECRET}".encode()).decode()
        data = urlencode({
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }).encode()
        req = Request("https://www.linkedin.com/oauth/v2/accessToken", data=data, method="POST")
        req.add_header("Authorization", f"Basic {auth}")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    elif slug == "reddit":
        auth = b64encode(f"{settings.REDDIT_CLIENT_ID}:{settings.REDDIT_CLIENT_SECRET}".encode()).decode()
        data = urlencode({
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }).encode()
        req = Request("https://www.reddit.com/api/v1/access_token", data=data, method="POST")
        req.add_header("Authorization", f"Basic {auth}")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("User-Agent", "GoalOS-Integrations-Manager/1.0")
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    elif slug == "twitter":
        data = urlencode({
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code_verifier": "",  # PKCE verifier would be stored in state
        }).encode()
        req = Request("https://api.twitter.com/2/oauth2/token", data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())

    raise HTTPException(status_code=400, detail=f"OAuth exchange not supported for {slug}")


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    code: str = Query(...),
    state: str = Query(None),
):
    """Handle OAuth callback from any provider."""
    db = _get_db(request)
    encryption = _get_encryption(request)

    # Validate state
    if state:
        oauth_states = getattr(request.app.state, "oauth_states", {})
        state_info = oauth_states.pop(state, None)
        if not state_info or state_info["expires"] < _dt.datetime.utcnow():
            raise HTTPException(status_code=400, detail="Invalid or expired OAuth state")
        if state_info["slug"] != provider:
            raise HTTPException(status_code=400, detail="State mismatch")

    # Find integration
    integration = db.query(Integration).filter(Integration.slug == provider).first()
    if not integration:
        raise HTTPException(status_code=404, detail=f"Integration '{provider}' not found")

    # Build redirect URI
    provider_mod = PROVIDER_REGISTRY.get(provider)
    if not provider_mod:
        raise HTTPException(status_code=404, detail=f"Provider '{provider}' not registered")
    oauth_config = provider_mod().get_oauth_config()
    redirect_uri = oauth_config.redirect_uri if oauth_config else ""

    # Exchange code for tokens
    try:
        token_data = await _exchange_code(provider, code, redirect_uri)
    except HTTPError as e:
        body = e.read().decode() if e.fp else str(e)
        raise HTTPException(status_code=400, detail=f"Token exchange failed: {body}")

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
    expires_at = _dt.datetime.utcnow() + _dt.timedelta(seconds=expires_in)

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
    status = db.query(ConnectionStatus).filter(
        ConnectionStatus.integration_id == integration.id
    ).first()
    if not status:
        status = ConnectionStatus(integration_id=integration.id)
        db.add(status)
    status.status = "connected"
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
