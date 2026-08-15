"""LinkedIn integration via the LinkedIn REST API (Posts API v2).

``LinkedInConnector`` talks to ``api.linkedin.com/rest`` over the shared
HTTP client using ``LINKEDIN_ACCESS_TOKEN`` with the organization owner
from ``LINKEDIN_ORGANIZATION_ID``. It supports organization metadata,
text post creation, post retrieval, and post deletion. Media uploads are
intentionally not implemented yet, and publishing only ever happens when
an explicit execution requests ``linkedin.create_text_post`` through the
approved workflow path (``PUBLISH_SOCIAL`` + approval gate).

Honesty contract:

- Missing ``LINKEDIN_ACCESS_TOKEN``/``LINKEDIN_ORGANIZATION_ID`` reports
  ``Not Configured``.
- HTTP 401 maps to :class:`AuthenticationError` (``AUTHENTICATION_FAILED``).
- HTTP 403 maps to :class:`PermissionDeniedError` (``PERMISSION_DENIED``).
- HTTP 429 maps to :class:`RateLimitError` (``RATE_LIMITED``).
- Reads require ``READ_SOCIAL``; creating/deleting posts require
  ``PUBLISH_SOCIAL`` (dangerous, never implicit).
- The access token is never logged and never returned in results.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar
from urllib.parse import quote

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

_LINKEDIN_API = "https://api.linkedin.com/rest"
_DEFAULT_API_VERSION = "202401"


class LinkedInConnector(IntegrationConnector):
    """LinkedIn connector for organizations and text posts."""

    required_env_vars: tuple[str, ...] = (
        "LINKEDIN_ACCESS_TOKEN",
        "LINKEDIN_ORGANIZATION_ID",
    )
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        "linkedin.health": Permission.READ_SOCIAL,
        "linkedin.get_organization": Permission.READ_SOCIAL,
        "linkedin.get_post": Permission.READ_SOCIAL,
        "linkedin.create_text_post": Permission.PUBLISH_SOCIAL,
        "linkedin.delete_post": Permission.PUBLISH_SOCIAL,
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        access_token: str | None = None,
        organization_id: str | None = None,
        api_version: str | None = None,
    ) -> None:
        super().__init__(
            name="linkedin",
            description="LinkedIn REST API integration (organizations and text posts)",
        )
        self.client = client or HttpClient()
        self.access_token = access_token or self._env("LINKEDIN_ACCESS_TOKEN") or ""
        self.organization_id = (
            organization_id or self._env("LINKEDIN_ORGANIZATION_ID") or ""
        )
        self.api_version = api_version or self._env("LINKEDIN_API_VERSION") or _DEFAULT_API_VERSION

    def _capabilities(self) -> tuple[str, ...]:
        return (
            "linkedin.health",
            "linkedin.get_organization",
            "linkedin.create_text_post",
            "linkedin.get_post",
            "linkedin.delete_post",
        )

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        missing = [
            name
            for name, value in (
                ("LINKEDIN_ACCESS_TOKEN", self.access_token),
                ("LINKEDIN_ORGANIZATION_ID", self.organization_id),
            )
            if not value
        ]
        if missing:
            return (
                ConnectorHealthStatus.NOT_CONFIGURED,
                f"missing environment configuration: {', '.join(missing)}",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability == "linkedin.health":
            return self._health()
        if capability == "linkedin.get_organization":
            return self._get_organization(params)
        if capability == "linkedin.create_text_post":
            return self._create_text_post(params)
        if capability == "linkedin.get_post":
            return self._get_post(params)
        if capability == "linkedin.delete_post":
            return self._delete_post(params)
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def _health(self) -> dict[str, Any]:
        status, message = self._configuration_status()
        return {
            "integration": "linkedin",
            "status": status.value,
            "configured": status.value == "Healthy",
            "message": message,
        }

    def _get_organization(self, params: dict[str, Any]) -> dict[str, Any]:
        organization_id = params.get("organization_id") or self.organization_id
        if not organization_id:
            raise ValueError("organization_id is required for linkedin.get_organization")
        response = self._fetch("GET", f"{_LINKEDIN_API}/organizations/{self._quote(organization_id)}")
        payload = self._decode(response, path="organizations")
        return {"organization_id": organization_id, "organization": payload}

    def _create_text_post(self, params: dict[str, Any]) -> dict[str, Any]:
        commentary = params.get("commentary") or params.get("text")
        if not commentary:
            raise ValueError("commentary is required for linkedin.create_text_post")
        visibility = params.get("visibility") or "PUBLIC"
        body: dict[str, Any] = {
            "author": f"urn:li:organization:{self.organization_id}",
            "commentary": str(commentary),
            "visibility": {"memberNetworkVisibility": str(visibility).upper()},
            "distribution": {"feedDistribution": "MAIN_FEED"},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        response = self._fetch(
            "POST",
            f"{_LINKEDIN_API}/posts",
            headers={"Content-Type": "application/json"},
            body=json.dumps(body).encode(),
        )
        payload = self._decode(response, path="posts", allow_empty=True)
        post_id = self._post_id(payload.get("id"))
        return {
            "created": True,
            "organization_id": self.organization_id,
            "post_id": post_id,
            "urn": payload.get("id"),
            "data": payload,
        }

    def _get_post(self, params: dict[str, Any]) -> dict[str, Any]:
        post_id = params.get("post_id")
        if not post_id:
            raise ValueError("post_id is required for linkedin.get_post")
        response = self._fetch("GET", f"{_LINKEDIN_API}/posts/{self._quote(self._post_id(post_id))}")
        payload = self._decode(response, path="posts")
        return {"post_id": self._post_id(post_id), "post": payload}

    def _delete_post(self, params: dict[str, Any]) -> dict[str, Any]:
        post_id = params.get("post_id")
        if not post_id:
            raise ValueError("post_id is required for linkedin.delete_post")
        response = self._fetch(
            "DELETE", f"{_LINKEDIN_API}/posts/{self._quote(self._post_id(post_id))}"
        )
        self._decode(response, path="posts", allow_empty=True)
        return {"deleted": True, "post_id": self._post_id(post_id)}

    # ------------------------------------------------------------------
    # Transport helpers
    # ------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "X-Restli-Protocol-Version": "2.0.0",
            "LinkedIn-Version": self.api_version,
        }

    def _fetch(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
    ) -> Any:
        """Issue one authenticated request with stable error mapping."""
        try:
            return self.client.fetch(
                url, method=method, headers={**self._headers(), **(headers or {})}, body=body
            )
        except HttpStatusError as exc:
            status = int(exc.status)
            if status == 401:
                raise AuthenticationError(
                    f"AUTHENTICATION_FAILED: LinkedIn returned HTTP 401 at {exc.url} "
                    "(check LINKEDIN_ACCESS_TOKEN)"
                ) from exc
            if status == 403:
                raise PermissionDeniedError(
                    f"PERMISSION_DENIED: LinkedIn returned HTTP 403 at {exc.url} "
                    "(insufficient token scopes or member permissions)"
                ) from exc
            if status == 429:
                raise RateLimitError(
                    f"RATE_LIMITED: LinkedIn returned HTTP 429 at {exc.url}"
                ) from exc
            raise ConnectorError(
                f"LinkedIn API error: HTTP {status} at {exc.url}"
            ) from exc

    def _decode(
        self, response: Any, *, path: str, allow_empty: bool = False
    ) -> dict[str, Any]:
        """Parse a LinkedIn response, mapping failures to distinct errors."""
        status = int(getattr(response, "status", 200) or 200)
        if status == 401:
            raise AuthenticationError(
                f"AUTHENTICATION_FAILED: LinkedIn returned HTTP 401 at {path} "
                "(check LINKEDIN_ACCESS_TOKEN)"
            )
        if status == 403:
            raise PermissionDeniedError(
                f"PERMISSION_DENIED: LinkedIn returned HTTP 403 at {path} "
                "(insufficient token scopes or member permissions)"
            )
        if status == 429:
            raise RateLimitError(f"RATE_LIMITED: LinkedIn returned HTTP 429 at {path}")
        if status >= 400:
            raise ConnectorError(
                f"LinkedIn API error: HTTP {status} at {path}: "
                f"{self._error_message(response.text)}"
            )
        if allow_empty and not response.text.strip():
            return {}
        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ConnectorError(
                f"invalid response from LinkedIn at {path}: "
                "response body is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ConnectorError(
                f"invalid response from LinkedIn at {path}: expected a JSON object"
            )
        if payload.get("status") and not payload.get("id"):
            raise ConnectorError(
                f"LinkedIn API error at {path}: {self._error_message(response.text)}"
            )
        return payload

    @staticmethod
    def _error_message(text: str) -> str:
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text[:300]
        if isinstance(payload, dict):
            message = payload.get("message") or payload.get("serviceErrorCode")
            if message:
                return str(message)[:300]
        return text[:300]

    @staticmethod
    def _post_id(value: Any) -> str:
        """Normalize a post URN (``urn:li:post:123``) to its numeric id."""
        text = str(value)
        if text.startswith("urn:li:"):
            return text.rsplit(":", 1)[-1]
        return text

    @staticmethod
    def _quote(value: str) -> str:
        return quote(value, safe="")
