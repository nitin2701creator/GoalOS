"""Google Analytics 4 (Data API) integration.

``GoogleAnalyticsConnector`` calls the GA4 Data API (``runReport`` /
``runRealtimeReport``) over the shared HTTP client using a service-account
access token. The token provider is injectable; without one (and without
the optional ``cryptography`` package for JWT signing) the connector
reports ``Authentication Required`` rather than pretending to work.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, ClassVar, Protocol

from app.agents.permissions import Permission
from app.integrations.exceptions import (
    AuthenticationError,
    CapabilityUnavailableError,
)
from app.integrations.http_client import HttpClient
from app.integrations.integration_connector import IntegrationConnector

TokenProvider = Callable[[], str]

_GA4_ENDPOINT = "https://analyticsdata.googleapis.com/v1beta"


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
    """GA4 Data API connector with normalized report output."""

    required_env_vars: tuple[str, ...] = ("GOALOS_GA4_PROPERTY_ID",)
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        "analytics.report": Permission.READ_ANALYTICS,
        "analytics.realtime": Permission.READ_ANALYTICS,
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        property_id: str | None = None,
        token_provider: AccessTokenProvider | None = None,
    ) -> None:
        super().__init__(
            name="google_analytics",
            description="Google Analytics 4 Data API integration",
        )
        self.client = client or HttpClient()
        self.property_id = property_id or self._env("GOALOS_GA4_PROPERTY_ID") or ""
        self.token_provider = token_provider or self._default_token_provider()

    def _default_token_provider(self) -> AccessTokenProvider | None:
        client_email = self._env("GOALOS_GA4_CLIENT_EMAIL")
        private_key = self._env("GOALOS_GA4_PRIVATE_KEY")
        if client_email and private_key:
            return ServiceAccountTokenProvider(client_email=client_email, private_key=private_key)
        return None

    def _capabilities(self) -> tuple[str, ...]:
        return ("analytics.report", "analytics.realtime")

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        if not self.property_id:
            return (
                ConnectorHealthStatus.NOT_CONFIGURED,
                "missing environment configuration: GOALOS_GA4_PROPERTY_ID",
            )
        if self.token_provider is None:
            return (
                ConnectorHealthStatus.AUTHENTICATION_REQUIRED,
                "GA4 credentials are required (GOALOS_GA4_CLIENT_EMAIL + GOALOS_GA4_PRIVATE_KEY)",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability == "analytics.report":
            return self._run_report(params, realtime=False)
        if capability == "analytics.realtime":
            return self._run_report(params, realtime=True)
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    def _run_report(self, params: dict[str, Any], *, realtime: bool) -> dict[str, Any]:
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

        endpoint = (
            f"{_GA4_ENDPOINT}/properties/{self.property_id}:runRealtimeReport"
            if realtime
            else f"{_GA4_ENDPOINT}/properties/{self.property_id}:runReport"
        )
        response = self.client.fetch(
            endpoint,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._token()}",
                "Content-Type": "application/json",
            },
            body=json.dumps(payload).encode(),
        )
        return self._normalize_report(response.text, realtime=realtime)

    def _token(self) -> str:
        if self.token_provider is None:
            raise AuthenticationError("GA4 token provider is not configured")
        return self.token_provider.get_token()

    @staticmethod
    def _normalize_report(text: str, *, realtime: bool) -> dict[str, Any]:
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
        return {
            "realtime": realtime,
            "dimensions": dimension_headers,
            "metrics": metric_headers,
            "rows": rows,
            "row_count": len(rows),
            "totals": payload.get("totals"),
            "property_id": payload.get("propertyQuota", {}),
        }
