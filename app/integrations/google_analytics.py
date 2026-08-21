"""Google Analytics 4 (Data API + Admin API) integration.

``GoogleAnalyticsConnector`` calls the GA4 Data API (``runReport`` /
``runRealtimeReport``) and the Admin API (``accountSummaries``) over
the shared HTTP client. It supports two authentication methods:

1. **Service account** (existing): ``GOALOS_GA4_CLIENT_EMAIL`` +
   ``GOALOS_GA4_PRIVATE_KEY`` for server-to-server access.
2. **OAuth 2.0** (new): Reuses the shared ``GOOGLE_CLIENT_ID`` /
   ``GOOGLE_CLIENT_SECRET`` / ``GOOGLE_REFRESH_TOKEN`` credentials
   via :class:`GoogleOAuthTokenProvider`. When OAuth is configured
   (and service account credentials are absent), the connector uses
   OAuth tokens — ideal for user-scoped GA4 property discovery.

Honesty contract:

- Missing credentials report ``Not Configured``.
- HTTP 401 maps to :class:`AuthenticationError` (``AUTHENTICATION_FAILED``).
- HTTP 403 maps to :class:`PermissionDeniedError` (``PERMISSION_DENIED``).
- HTTP 429 maps to :class:`RateLimitError` (``RATE_LIMITED``).
- Malformed responses raise structured errors so the execution runtime
  persists a real failure — availability is never fabricated.

Configuration:

- ``GOALOS_GA4_PROPERTY_ID`` — single-property ID for reports (optional
  when using ``analytics.list_properties`` to discover properties).
- ``GOALOS_GA4_CLIENT_EMAIL`` + ``GOALOS_GA4_PRIVATE_KEY`` — service
  account credentials (optional when OAuth is configured).
- ``GOOGLE_CLIENT_ID`` + ``GOOGLE_CLIENT_SECRET`` + ``GOOGLE_REFRESH_TOKEN``
  — OAuth credentials (optional when service account is configured).

Capabilities:

- ``analytics.health`` — configuration/health check
- ``analytics.list_properties`` — discover GA4 properties (Admin API)
- ``analytics.report`` — standard report with date range
- ``analytics.realtime`` — real-time report
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, ClassVar, Protocol

from app.agents.permissions import Permission
from app.integrations.exceptions import (
    AuthenticationError,
    CapabilityUnavailableError,
    ConnectorError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.http_client import HttpClient, HttpStatusError
from app.integrations.integration_connector import IntegrationConnector

TokenProvider = Callable[[], str]

_GA4_DATA_ENDPOINT = "https://analyticsdata.googleapis.com/v1beta"
_GA4_ADMIN_ENDPOINT = "https://analyticsadmin.googleapis.com/v1beta"


class AccessTokenProvider(Protocol):
    """Provides a bearer token for Google APIs."""

    def get_token(self) -> str: ...


class ServiceAccountTokenProvider:
    """Service-account access token via JWT assertion (RS256).

    Requires the ``cryptography`` package at call time. Without it the
    provider raises :class:`AuthenticationError` so configuration state is
    reported honestly.
    """

    def __init__(
        self,
        *,
        client_email: str | None = None,
        private_key: str | None = None,
    ) -> None:
        self.client_email = client_email or self._env("GOALOS_GA4_CLIENT_EMAIL") or ""
        self.private_key = private_key or self._env("GOALOS_GA4_PRIVATE_KEY") or ""

    def get_token(self) -> str:
        if not self.client_email or not self.private_key:
            raise AuthenticationError(
                "GA4 service account credentials are not configured"
            )
        try:
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise AuthenticationError(
                "GA4 service-account JWT signing requires the 'cryptography' "
                "package or an injected token provider"
            ) from exc

        import base64
        import time

        def _b64url(data: bytes) -> str:
            return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

        header = {"alg": "RS256", "typ": "JWT"}
        now = int(time.time())
        claims = {
            "iss": self.client_email,
            "scope": "https://www.googleapis.com/auth/analytics.readonly",
            "aud": "https://oauth2.googleapis.com/token",
            "iat": now,
            "exp": now + 3600,
        }
        signing_input = (
            f"{_b64url(json.dumps(header).encode())}."
            f"{_b64url(json.dumps(claims).encode())}"
        )
        private_key = serialization.load_pem_private_key(
            self.private_key.encode(), password=None
        )
        signature = private_key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
        assertion = f"{signing_input}.{_b64url(signature)}"

        client = HttpClient()
        response = client.fetch(
            "https://oauth2.googleapis.com/token",
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            body=f"grant_type=urn%3Aietf%3Aparams%3Aoauth%3Agrant-type%3Ajwt-bearer&assertion={assertion}".encode(),
        )
        payload = json.loads(response.text)
        token = payload.get("access_token")
        if not token:
            raise AuthenticationError("GA4 token endpoint returned no access token")
        return str(token)

    @staticmethod
    def _env(name: str) -> str | None:
        import os

        value = os.environ.get(name)
        return value.strip() if value and value.strip() else None


class GoogleAnalyticsConnector(IntegrationConnector):
    """GA4 Data API + Admin API connector with normalized report output.

    Supports both service-account and OAuth 2.0 authentication.
    OAuth is preferred when GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN are set.
    """

    required_env_vars: tuple[str, ...] = ()
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        "analytics.health": Permission.READ_ANALYTICS,
        "analytics.list_properties": Permission.READ_ANALYTICS,
        "analytics.report": Permission.READ_ANALYTICS,
        "analytics.realtime": Permission.READ_ANALYTICS,
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        property_id: str | None = None,
        token_provider: AccessTokenProvider | None = None,
        oauth_token_provider: Any | None = None,
    ) -> None:
        super().__init__(
            name="google_analytics",
            description="Google Analytics 4 Data API + Admin API integration",
        )
        self.client = client or HttpClient()
        self.property_id = property_id or self._env("GOALOS_GA4_PROPERTY_ID") or ""
        self._oauth_token_provider = oauth_token_provider or self._build_oauth_provider()
        self.token_provider = token_provider or self._default_token_provider()

    def _build_oauth_provider(self) -> Any | None:
        """Build an OAuth token provider if Google OAuth credentials are present."""
        import os

        client_id = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
        client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
        refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "").strip()
        if not (client_id and client_secret and refresh_token):
            return None
        from app.integrations.google_auth import GoogleOAuthTokenProvider

        return GoogleOAuthTokenProvider(
            client=self.client,
            scope="https://www.googleapis.com/auth/analytics.readonly",
        )

    def _default_token_provider(self) -> AccessTokenProvider | None:
        client_email = self._env("GOALOS_GA4_CLIENT_EMAIL")
        private_key = self._env("GOALOS_GA4_PRIVATE_KEY")
        if client_email and private_key:
            return ServiceAccountTokenProvider(client_email=client_email, private_key=private_key)
        return None

    def _capabilities(self) -> tuple[str, ...]:
        return (
            "analytics.health",
            "analytics.list_properties",
            "analytics.report",
            "analytics.realtime",
        )

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        # Check if OAuth is configured
        oauth_configured = self._oauth_token_provider is not None and self._oauth_token_provider.is_configured
        # Check if service account is configured
        sa_configured = self.token_provider is not None

        if not oauth_configured and not sa_configured:
            return (
                ConnectorHealthStatus.AUTHENTICATION_REQUIRED,
                "GA4 credentials are required: either GOOGLE_CLIENT_ID + "
                "GOOGLE_CLIENT_SECRET + GOOGLE_REFRESH_TOKEN (OAuth) or "
                "GOALOS_GA4_CLIENT_EMAIL + GOALOS_GA4_PRIVATE_KEY (service account)",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    def _has_oauth(self) -> bool:
        """Return whether OAuth-based authentication is available."""
        return self._oauth_token_provider is not None and self._oauth_token_provider.is_configured

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability == "analytics.health":
            return self._health()
        if capability == "analytics.list_properties":
            return self._list_properties(params)
        if capability == "analytics.report":
            return self._run_report(params, realtime=False)
        if capability == "analytics.realtime":
            return self._run_report(params, realtime=True)
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def _health(self) -> dict[str, Any]:
        from app.integrations.connector_health import ConnectorHealthStatus

        status, message = self._configuration_status()
        auth_method = "oauth" if self._has_oauth() else "service_account" if self.token_provider else "none"
        return {
            "integration": "google_analytics",
            "status": status.value,
            "configured": status is ConnectorHealthStatus.HEALTHY,
            "auth_method": auth_method,
            "property_id": self.property_id or None,
            "message": message,
        }

    def _list_properties(self, params: dict[str, Any]) -> dict[str, Any]:
        """Discover GA4 properties via the Admin API ``accountSummaries``.

        Uses OAuth when available (user-scoped access), falling back to
        service account auth.
        """
        query: dict[str, Any] = {
            "pageSize": str(min(int(params.get("page_size") or 200), 200)),
        }
        if params.get("page_token"):
            query["pageToken"] = params["page_token"]

        response = self._fetch(
            "GET",
            f"{_GA4_ADMIN_ENDPOINT}/accountSummaries",
            params=query,
        )
        payload = self._decode(response, path="accountSummaries")
        account_summaries = payload.get("accountSummaries") or []

        properties: list[dict[str, Any]] = []
        for account in account_summaries:
            if not isinstance(account, dict):
                continue
            account_id = account.get("account", "")
            account_name = account.get("displayName", "")
            for prop in account.get("propertySummaries") or []:
                if not isinstance(prop, dict):
                    continue
                properties.append({
                    "property_id": prop.get("property", ""),
                    "display_name": prop.get("displayName", ""),
                    "property_type": prop.get("propertyType", ""),
                    "account_id": account_id,
                    "account_name": account_name,
                    "firebase_project_id": prop.get("firebaseProjectId", ""),
                })

        return {
            "total": len(properties),
            "next_page_token": payload.get("nextPageToken"),
            "properties": properties,
        }

    def _run_report(self, params: dict[str, Any], *, realtime: bool) -> dict[str, Any]:
        property_id = params.get("property_id") or self.property_id
        if not property_id:
            raise CapabilityUnavailableError(
                "GA4 property_id is required: set GOALOS_GA4_PROPERTY_ID "
                "or pass property_id in params"
            )

        payload: dict[str, Any] = {}
        if not realtime:
            payload["dateRanges"] = [
                {
                    "startDate": params.get("start_date") or "30daysAgo",
                    "endDate": params.get("end_date") or "today",
                }
            ]

        dimensions = params.get("dimensions") or ["date"]
        metrics = params.get("metrics") or ["sessions", "totalUsers"]
        payload["dimensions"] = [{"name": name} for name in dimensions]
        payload["metrics"] = [{"name": name} for name in metrics]

        if params.get("dimension_filter"):
            payload["dimensionFilter"] = params["dimension_filter"]
        if params.get("metric_filter"):
            payload["metricFilter"] = params["metric_filter"]
        if params.get("order_bys"):
            payload["orderBys"] = params["order_bys"]
        if params.get("limit"):
            payload["limit"] = int(params["limit"])

        endpoint = (
            f"{_GA4_DATA_ENDPOINT}/properties/{property_id}:runRealtimeReport"
            if realtime
            else f"{_GA4_DATA_ENDPOINT}/properties/{property_id}:runReport"
        )
        response = self._fetch(
            "POST",
            endpoint,
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload).encode(),
        )
        return self._normalize_report(response.text, realtime=realtime, property_id=property_id)

    # ------------------------------------------------------------------
    # Auth + HTTP
    # ------------------------------------------------------------------
    def _token(self) -> str:
        """Return an access token, preferring OAuth when available."""
        if self._has_oauth():
            try:
                return self._oauth_token_provider.get_token()
            except Exception:
                pass  # Fall through to service account
        if self.token_provider is not None:
            return self.token_provider.get_token()
        raise AuthenticationError(
            "AUTHENTICATION_FAILED: GA4 token provider is not configured"
        )

    def _fetch(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Issue one authenticated request with stable error mapping."""
        request_headers = {"Authorization": f"Bearer {self._token()}"}
        if headers:
            request_headers.update(headers)
        try:
            return self.client.fetch(
                url, method=method, headers=request_headers, body=body, params=params
            )
        except HttpStatusError as exc:
            status = int(exc.status)
            if status == 401:
                raise AuthenticationError(
                    f"AUTHENTICATION_FAILED: Google Analytics returned HTTP 401 "
                    f"at {exc.url} (token invalid or expired)"
                ) from exc
            if status == 403:
                raise PermissionDeniedError(
                    f"PERMISSION_DENIED: Google Analytics returned HTTP 403 at "
                    f"{exc.url} (insufficient OAuth scope or permissions)"
                ) from exc
            if status == 429:
                raise RateLimitError(
                    f"RATE_LIMITED: Google Analytics returned HTTP 429 at {exc.url}"
                ) from exc
            raise ConnectorError(
                f"Google Analytics API error: HTTP {status} at {exc.url}"
            ) from exc

    def _decode(self, response: Any, *, path: str, allow_empty: bool = False) -> dict[str, Any]:
        """Parse a GA4 API response, mapping failures to distinct errors."""
        status = int(getattr(response, "status", 200) or 200)
        if status == 401:
            raise AuthenticationError(
                f"AUTHENTICATION_FAILED: Google Analytics returned HTTP 401 at {path}"
            )
        if status == 403:
            raise PermissionDeniedError(
                f"PERMISSION_DENIED: Google Analytics returned HTTP 403 at {path}"
            )
        if status == 429:
            raise RateLimitError(f"RATE_LIMITED: Google Analytics returned HTTP 429 at {path}")
        if status >= 400:
            try:
                error_body = json.loads(response.text)
                error_msg = error_body.get("error", {}).get("message", response.text[:300])
            except Exception:
                error_msg = response.text[:300]
            raise ConnectorError(
                f"Google Analytics API error: HTTP {status} at {path}: {error_msg}"
            )
        if allow_empty and not response.text.strip():
            return {}
        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ConnectorError(
                f"invalid response from Google Analytics at {path}: "
                "response body is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ConnectorError(
                f"invalid response from Google Analytics at {path}: "
                "expected a JSON object"
            )
        return payload

    # ------------------------------------------------------------------
    # Report normalization
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_report(text: str, *, realtime: bool, property_id: str = "") -> dict[str, Any]:
        payload = json.loads(text)
        dimension_headers = [item.get("name", "") for item in payload.get("dimensionHeaders", [])]
        metric_headers = [item.get("name", "") for item in payload.get("metricHeaders", [])]
        rows: list[dict[str, Any]] = []
        for row in payload.get("rows", []):
            normalized: dict[str, Any] = {}
            for dimension, value in zip(dimension_headers, row.get("dimensionValues", [])):
                normalized[dimension] = value.get("value")
            for metric, value in zip(metric_headers, row.get("metricValues", [])):
                normalized[metric] = value.get("value")
            rows.append(normalized)

        # Build summary from totals row if present
        summary: dict[str, Any] = {}
        totals = payload.get("totals")
        if totals and isinstance(totals, list) and totals:
            total_row = totals[0]
            for dimension, value in zip(dimension_headers, total_row.get("dimensionValues", [])):
                summary[dimension] = value.get("value")
            for metric, value in zip(metric_headers, total_row.get("metricValues", [])):
                summary[metric] = value.get("value")

        return {
            "realtime": realtime,
            "property_id": property_id,
            "dimensions": dimension_headers,
            "metrics": metric_headers,
            "rows": rows,
            "row_count": len(rows),
            "summary": summary,
            "metadata": payload.get("metadata"),
            "property_quota": payload.get("propertyQuota"),
        }
