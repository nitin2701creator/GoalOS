"""Twenty CRM integration: REST API reads and permission-gated writes.

``TwentyConnector`` talks to Twenty's schema-generated REST API (``/rest/``)
over the shared HTTP client with ``Authorization: Bearer <API key>`` from
environment configuration. The base URL is fully configurable so it works
against both Twenty Cloud (``https://api.twenty.com``) and self-hosted
workspaces (``https://{your-domain}``); custom-object endpoints are never
assumed — reads/writes target the standard core objects (people, companies,
opportunities, tasks, notes) with the caller-supplied field values.

Honesty contract:

- Missing ``GOALOS_TWENTY_BASE_URL``/``GOALOS_TWENTY_API_KEY`` reports
  ``Not Configured`` — never a fake success.
- HTTP 401/403 maps to :class:`AuthenticationError` (distinct from other
  failures).
- HTTP 429 maps to :class:`RateLimitError`.
- Other non-success statuses and malformed responses raise structured
  errors so the execution runtime persists a real failure.
- Reads require ``READ_CRM``; every create/update requires ``WRITE_CRM``
  (a dangerous permission that is never granted implicitly).
- API keys are never logged.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar
from urllib.parse import urljoin

from app.agents.permissions import Permission
from app.integrations.exceptions import (
    AuthenticationError,
    CapabilityUnavailableError,
    ConnectorError,
    RateLimitError,
)
from app.integrations.http_client import HttpClient, HttpStatusError
from app.integrations.integration_connector import IntegrationConnector

#: Capability → standard Twenty core object slug.
_CAPABILITY_OBJECTS: dict[str, str] = {
    "twenty.search_people": "people",
    "twenty.create_person": "people",
    "twenty.update_person": "people",
    "twenty.search_companies": "companies",
    "twenty.create_company": "companies",
    "twenty.update_company": "companies",
    "twenty.search_opportunities": "opportunities",
    "twenty.create_opportunity": "opportunities",
    "twenty.update_opportunity": "opportunities",
    "twenty.create_task": "tasks",
    "twenty.update_task": "tasks",
    "twenty.create_note": "notes",
}

#: Standard core-object fields searched by ``query`` (not custom fields —
#: workspace-specific fields are passed through via ``filter`` instead).
_SEARCH_FIELDS: dict[str, tuple[str, ...]] = {
    "people": ("firstName", "lastName", "email"),
    "companies": ("name", "domainName"),
    "opportunities": ("name",),
    "tasks": ("title",),
    "notes": ("title",),
}

_READ_CAPABILITIES = frozenset(
    {
        "twenty.search_people",
        "twenty.search_companies",
        "twenty.search_opportunities",
        "twenty.get_record",
    }
)


class TwentyConnector(IntegrationConnector):
    """Twenty CRM connector for people, companies, opportunities, tasks, notes."""

    required_env_vars: tuple[str, ...] = (
        "GOALOS_TWENTY_BASE_URL",
        "GOALOS_TWENTY_API_KEY",
    )
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        capability: (
            Permission.READ_CRM if capability in _READ_CAPABILITIES else Permission.WRITE_CRM
        )
        for capability in (
            *(_CAPABILITY_OBJECTS.keys()),
            "twenty.get_record",
        )
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        super().__init__(
            name="twenty",
            description="Twenty CRM REST API integration",
        )
        self.client = client or HttpClient()
        self.base_url = (base_url or self._env("GOALOS_TWENTY_BASE_URL") or "").rstrip("/")
        self.api_key = api_key or self._env("GOALOS_TWENTY_API_KEY") or ""

    def _capabilities(self) -> tuple[str, ...]:
        return (
            "twenty.search_people",
            "twenty.create_person",
            "twenty.update_person",
            "twenty.search_companies",
            "twenty.create_company",
            "twenty.update_company",
            "twenty.search_opportunities",
            "twenty.create_opportunity",
            "twenty.update_opportunity",
            "twenty.create_task",
            "twenty.update_task",
            "twenty.create_note",
            "twenty.get_record",
        )

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        missing = [
            name
            for name, value in (
                ("GOALOS_TWENTY_BASE_URL", self.base_url),
                ("GOALOS_TWENTY_API_KEY", self.api_key),
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
        if capability == "twenty.get_record":
            return self._get_record(params)
        if capability.startswith("twenty.search_"):
            return self._search(_CAPABILITY_OBJECTS[capability], params)
        if capability.startswith("twenty.create_"):
            return self._create(_CAPABILITY_OBJECTS[capability], params)
        if capability.startswith("twenty.update_"):
            return self._update(_CAPABILITY_OBJECTS[capability], params)
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def _search(self, object_slug: str, params: dict[str, Any]) -> dict[str, Any]:
        """List records of ``object_slug`` with optional query/filter/limit."""
        query: dict[str, Any] = {}
        if params.get("filter"):
            query["filter"] = self._dumps(params["filter"])
        elif params.get("query"):
            query["filter"] = self._dumps(self._query_filter(object_slug, params["query"]))
        if params.get("limit"):
            query["limit"] = int(params["limit"])
        if params.get("offset"):
            query["offset"] = int(params["offset"])
        if params.get("order_by"):
            query["order_by"] = params["order_by"]
        response = self._fetch("GET", self._url(object_slug), headers=self._headers(), params=query)
        payload = self._decode(response, path=f"/rest/{object_slug}")
        data = payload.get("data")
        if isinstance(data, list):
            return {
                "object": object_slug,
                "total": payload.get("totalCount", len(data)),
                "items": data,
            }
        if isinstance(data, dict):
            return {"object": object_slug, "total": 1, "items": [data]}
        return {"object": object_slug, "total": 0, "items": []}

    def _create(self, object_slug: str, params: dict[str, Any]) -> dict[str, Any]:
        """Create one record; field values come from ``fields`` (or top-level)."""
        fields = params.get("fields") or {
            key: value
            for key, value in params.items()
            if key not in ("fields", "object", "object_id", "id")
        }
        response = self._fetch(
            "POST",
            self._url(object_slug),
            headers={**self._headers(), "Content-Type": "application/json"},
            body=self._dumps(fields).encode(),
        )
        payload = self._decode(response, path=f"/rest/{object_slug}")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        return {"object": object_slug, "created": True, "data": data}

    def _update(self, object_slug: str, params: dict[str, Any]) -> dict[str, Any]:
        """Update one record by id; field values come from ``fields``."""
        record_id = params.get("id") or params.get("object_id")
        if not record_id:
            raise ValueError(f"id is required to update {object_slug}")
        fields = params.get("fields") or {
            key: value
            for key, value in params.items()
            if key not in ("fields", "object", "object_id", "id")
        }
        response = self._fetch(
            "PATCH",
            self._url(f"{object_slug}/{record_id}"),
            headers={**self._headers(), "Content-Type": "application/json"},
            body=self._dumps(fields).encode(),
        )
        payload = self._decode(response, path=f"/rest/{object_slug}/{record_id}")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        return {"object": object_slug, "updated": True, "id": str(record_id), "data": data}

    def _get_record(self, params: dict[str, Any]) -> dict[str, Any]:
        """Fetch a single record by object slug + id (any object, incl. custom)."""
        object_slug = params.get("object") or params.get("object_type")
        record_id = params.get("id") or params.get("object_id")
        if not object_slug or not record_id:
            raise ValueError("object and id are required for twenty.get_record")
        response = self._fetch(
            "GET",
            self._url(f"{object_slug}/{record_id}"),
            headers=self._headers(),
        )
        payload = self._decode(response, path=f"/rest/{object_slug}/{record_id}")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        return {"object": object_slug, "id": str(record_id), "data": data}

    # ------------------------------------------------------------------
    # Transport helpers
    # ------------------------------------------------------------------
    def _query_filter(self, object_slug: str, query: str) -> dict[str, Any]:
        """Build a standard-field filter for a free-text ``query``."""
        clauses = [
            {field: {"ilike": f"%{query}%"}}
            for field in _SEARCH_FIELDS.get(object_slug, ("name",))
        ]
        if len(clauses) == 1:
            return clauses[0]
        return {"or": clauses}

    def _fetch(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        body: bytes | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Issue a request, mapping transport 4xx failures to distinct errors.

        The shared client returns 4xx responses as-is when the opener raises
        ``HTTPError`` (real ``urllib``), but raises :class:`HttpStatusError`
        for returned non-success responses. Both paths are mapped here so
        auth failures and rate limits are always distinct and structured.
        """
        try:
            return self.client.fetch(url, method=method, headers=headers, body=body, params=params)
        except HttpStatusError as exc:
            status = int(exc.status)
            if status in (401, 403):
                raise AuthenticationError(
                    f"AUTHENTICATION_FAILED: HTTP {status} from Twenty at {exc.url} "
                    "(check GOALOS_TWENTY_API_KEY)"
                ) from exc
            if status == 429:
                raise RateLimitError(
                    f"RATE_LIMITED: Twenty returned HTTP 429 at {exc.url} "
                    "(100 requests/minute limit)"
                ) from exc
            raise ConnectorError(
                f"Twenty API error: HTTP {status} at {exc.url}"
            ) from exc

    def _url(self, path: str) -> str:
        return urljoin(f"{self.base_url}/rest/", path.lstrip("/"))

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _decode(self, response: Any, *, path: str) -> dict[str, Any]:
        """Parse a Twenty response, mapping status/JSON failures to distinct errors.

        Raises:
            AuthenticationError: HTTP 401/403 (invalid/expired API key).
            RateLimitError: HTTP 429 (Twenty limits to 100 requests/minute).
            ConnectorError: Other non-success statuses or malformed payloads.
        """
        status = int(getattr(response, "status", 200) or 200)
        if status in (401, 403):
            raise AuthenticationError(
                f"AUTHENTICATION_FAILED: HTTP {status} from Twenty at {path} "
                "(check GOALOS_TWENTY_API_KEY)"
            )
        if status == 429:
            raise RateLimitError(
                f"RATE_LIMITED: Twenty returned HTTP 429 at {path} "
                "(100 requests/minute limit)"
            )
        if status >= 400:
            message = self._error_message(response.text)
            raise ConnectorError(
                f"Twenty API error: HTTP {status} at {path}: {message}"
            )
        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ConnectorError(
                f"invalid response from Twenty at {path}: "
                "response body is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ConnectorError(
                f"invalid response from Twenty at {path}: expected a JSON object"
            )
        if isinstance(payload.get("error"), dict):
            error = payload["error"]
            raise ConnectorError(
                f"Twenty API error at {path}: "
                f"{error.get('message') or error.get('code') or error}"
            )
        return payload

    @staticmethod
    def _error_message(text: str) -> str:
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text[:500]
        if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
            return str(payload["error"].get("message") or payload["error"])[:500]
        if isinstance(payload, dict) and payload.get("message"):
            return str(payload["message"])[:500]
        return text[:500]

    @staticmethod
    def _dumps(payload: Any) -> str:
        return json.dumps(payload)
