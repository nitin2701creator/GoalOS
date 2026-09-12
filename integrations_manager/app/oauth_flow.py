"""Provider-aware OAuth flows for the Integrations Manager.

Implements the shared parts of OAuth 2.0:

* RFC 7636 PKCE generation (``generate_pkce_pair``).
* Authorization-URL building with a mandatory, persisted CSRF ``state``
  and an encrypted PKCE ``code_verifier`` (``build_authorization_url``).
* Authorization-code exchange (``exchange_code``).
* Access-token refresh from stored refresh tokens (``refresh_access_token``).

Every network call goes through the GoalOS :class:`HttpClient` so requests
are bounded (timeout, size cap) and testable via an injected opener. No
secret is ever logged or returned to callers other than the token payload.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import secrets as _secrets
from urllib.parse import urlencode

from app.integrations.http_client import HttpClient, HttpError

from integrations_manager.app.config import settings
from integrations_manager.app.models import OAuthState

#: Providers whose authorization endpoint requires PKCE (RFC 7636).
PKCE_PROVIDERS = frozenset({"twitter"})

#: Providers whose token endpoint accepts a ``refresh_token`` grant.
REFRESHABLE_PROVIDERS = frozenset({"google_analytics", "linkedin", "reddit", "twitter"})

#: State lifetime for a pending authorization flow.
STATE_TTL = _dt.timedelta(minutes=10)


class OAuthNotConfiguredError(Exception):
    """Raised when a provider's OAuth client credentials are missing."""


class OAuthExchangeError(Exception):
    """Raised when a token endpoint rejects an exchange or refresh."""


def _client_credentials(slug: str) -> tuple[str, str]:
    """Return ``(client_id, client_secret)`` for an OAuth provider."""
    mapping = {
        "google_analytics": (settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET),
        "meta": (settings.META_APP_ID, settings.META_APP_SECRET),
        "linkedin": (settings.LINKEDIN_CLIENT_ID, settings.LINKEDIN_CLIENT_SECRET),
        "reddit": (settings.REDDIT_CLIENT_ID, settings.REDDIT_CLIENT_SECRET),
        "twitter": (settings.TWITTER_CLIENT_ID, settings.TWITTER_CLIENT_SECRET),
    }
    return mapping.get(slug, ("", ""))


def require_client_id(slug: str) -> str:
    """Return the client ID for ``slug`` or fail fast when not configured.

    Raises:
        OAuthNotConfiguredError: If the provider has no client ID set.
    """
    client_id, _ = _client_credentials(slug)
    if not client_id:
        raise OAuthNotConfiguredError(
            f"OAuth client credentials are not configured for '{slug}'"
        )
    return client_id


def get_client_credentials(slug: str) -> tuple[str, str]:
    """Return ``(client_id, client_secret)`` for ``slug`` (may be empty)."""
    return _client_credentials(slug)


def generate_pkce_pair() -> tuple[str, str]:
    """Return ``(code_verifier, code_challenge)`` for RFC 7636 ``S256``.

    The verifier uses the unreserved URL-safe alphabet, 43–128 chars,
    exactly as required by the spec.
    """
    verifier = _secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_authorization_url(
    *,
    slug: str,
    auth_url: str,
    redirect_uri: str,
    scopes: list[str],
    db,
    encryption,
    extra_params: dict[str, str] | None = None,
) -> str:
    """Persist a fresh OAuth state and return the authorization URL.

    The ``state`` and (for PKCE providers) the encrypted ``code_verifier``
    are stored in the database so the callback can validate the state,
    enforce one-time use, and complete the token exchange with the exact
    redirect URI and verifier used to build this URL.
    """
    state = _secrets.token_urlsafe(32)
    code_verifier = None
    code_challenge: str | None = None
    if slug in PKCE_PROVIDERS:
        code_verifier, code_challenge = generate_pkce_pair()

    params: dict[str, str] = {
        "client_id": require_client_id(slug),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    if code_verifier is not None:
        params["code_challenge"] = code_challenge or ""
        params["code_challenge_method"] = "S256"
    if extra_params:
        params.update(extra_params)

    encrypted_verifier: str | None = None
    if code_verifier is not None:
        encrypted_verifier = encryption.encrypt(code_verifier)

    db.add(OAuthState(
        state=state,
        provider=slug,
        redirect_uri=redirect_uri,
        encrypted_code_verifier=encrypted_verifier,
        expires_at=_dt.datetime.utcnow() + STATE_TTL,
    ))
    db.commit()

    return f"{auth_url}?{urlencode(params)}"


def supports_refresh(slug: str) -> bool:
    """Return True when ``slug`` can refresh tokens from a refresh token."""
    return slug in REFRESHABLE_PROVIDERS


def _token_request(
    client: HttpClient,
    url: str,
    data: dict[str, str],
    *,
    basic_auth: tuple[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    """POST ``application/x-www-form-urlencoded`` data and parse JSON.

    Raises:
        OAuthExchangeError: If the endpoint returns a non-success status.
        HttpError: For transport-level failures.
    """
    request_headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if basic_auth:
        raw = f"{basic_auth[0]}:{basic_auth[1]}".encode()
        request_headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    if headers:
        request_headers.update(headers)

    response = client.fetch(
        url,
        method="POST",
        headers=request_headers,
        body=urlencode(data).encode(),
    )
    payload: dict = {}
    if response.text.strip():
        try:
            payload = json.loads(response.text)
        except (ValueError, TypeError):
            payload = {}
    if response.status >= 400:
        description = (
            payload.get("error_description")
            or payload.get("error")
            or (payload.get("detail") if isinstance(payload.get("detail"), str) else "")
            or f"HTTP {response.status}"
        )
        raise OAuthExchangeError(str(description))
    return payload


def exchange_code(
    slug: str,
    code: str,
    redirect_uri: str,
    code_verifier: str | None = None,
    client: HttpClient | None = None,
) -> dict:
    """Exchange an authorization code for tokens (provider-specific)."""
    client = client or HttpClient()
    client_id, client_secret = _client_credentials(slug)

    if slug == "google_analytics":
        require_client_id(slug)
        return _token_request(client, "https://oauth2.googleapis.com/token", {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })

    if slug == "meta":
        require_client_id(slug)
        params = {
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
        }
        response = client.get(
            "https://graph.facebook.com/v19.0/oauth/access_token",
            params=params,
        )
        payload: dict = {}
        if response.text.strip():
            try:
                payload = json.loads(response.text)
            except (ValueError, TypeError):
                payload = {}
        if response.status >= 400:
            raise OAuthExchangeError(
                str(payload.get("error") or payload.get("error_message") or f"HTTP {response.status}")
            )
        return payload

    if slug == "linkedin":
        require_client_id(slug)
        return _token_request(
            client,
            "https://www.linkedin.com/oauth/v2/accessToken",
            {"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri},
            basic_auth=(client_id, client_secret),
        )

    if slug == "reddit":
        require_client_id(slug)
        return _token_request(
            client,
            "https://www.reddit.com/api/v1/access_token",
            {"code": code, "grant_type": "authorization_code", "redirect_uri": redirect_uri},
            basic_auth=(client_id, client_secret),
            headers={"User-Agent": "GoalOS-Integrations-Manager/1.0"},
        )

    if slug == "twitter":
        require_client_id(slug)
        if not code_verifier:
            raise OAuthExchangeError("PKCE code_verifier missing for X/Twitter")
        data = {
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        }
        basic_auth = (client_id, client_secret) if client_secret else None
        return _token_request(
            client,
            "https://api.twitter.com/2/oauth2/token",
            data,
            basic_auth=basic_auth,
        )

    raise OAuthExchangeError(f"OAuth exchange not supported for {slug}")


def refresh_access_token(
    slug: str,
    refresh_token: str,
    client: HttpClient | None = None,
) -> dict:
    """Refresh an access token using the provider's refresh grant.

    Raises:
        OAuthExchangeError: If the provider does not support refresh or the
            endpoint rejects the request.
    """
    if not supports_refresh(slug):
        raise OAuthExchangeError(f"Token refresh not supported for {slug}")

    client = client or HttpClient()
    client_id, client_secret = _client_credentials(slug)

    if slug == "google_analytics":
        require_client_id(slug)
        return _token_request(client, "https://oauth2.googleapis.com/token", {
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        })

    if slug == "linkedin":
        require_client_id(slug)
        return _token_request(
            client,
            "https://www.linkedin.com/oauth/v2/accessToken",
            {"refresh_token": refresh_token, "grant_type": "refresh_token"},
            basic_auth=(client_id, client_secret),
        )

    if slug == "reddit":
        require_client_id(slug)
        return _token_request(
            client,
            "https://www.reddit.com/api/v1/access_token",
            {"refresh_token": refresh_token, "grant_type": "refresh_token"},
            basic_auth=(client_id, client_secret),
            headers={"User-Agent": "GoalOS-Integrations-Manager/1.0"},
        )

    if slug == "twitter":
        require_client_id(slug)
        data = {
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "client_id": client_id,
        }
        basic_auth = (client_id, client_secret) if client_secret else None
        return _token_request(
            client,
            "https://api.twitter.com/2/oauth2/token",
            data,
            basic_auth=basic_auth,
        )

    raise OAuthExchangeError(f"OAuth exchange not supported for {slug}")


def apply_refreshed_tokens(token_row, encryption, token_data: dict, now: _dt.datetime | None = None) -> str:
    """Persist refreshed tokens onto ``token_row`` and return the access token.

    Replaces the encrypted access token, optionally rotates the refresh
    token when the provider returns a new one, and advances ``expires_at``.
    """
    now = now or _dt.datetime.utcnow()
    access_token = token_data.get("access_token") or ""
    if not access_token:
        raise OAuthExchangeError("No access_token in refresh response")

    expires_in = token_data.get("expires_in")
    try:
        expires_in_seconds = int(expires_in) if expires_in is not None else 3600
    except (TypeError, ValueError):
        expires_in_seconds = 3600

    token_row.encrypted_access_token = encryption.encrypt(access_token)
    new_refresh = token_data.get("refresh_token")
    if new_refresh:
        token_row.encrypted_refresh_token = encryption.encrypt(new_refresh)
    token_row.expires_at = now + _dt.timedelta(seconds=expires_in_seconds)
    token_row.scopes = token_data.get("scope", token_row.scopes or "")
    return access_token