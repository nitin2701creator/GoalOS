"""Google Calendar integration via the Calendar API v3.

``GoogleCalendarConnector`` talks to ``www.googleapis.com/calendar/v3``
over the shared HTTP client using the shared Google OAuth token service
(``app.integrations.google_auth``). The connector supports calendar
discovery, event search/retrieval, event create/update/delete with
attendees and timezone-aware start/end times, and free/busy lookups.

Honesty contract:

- Missing Google OAuth configuration reports ``Not Configured``.
- HTTP 401 maps to :class:`AuthenticationError` (``AUTHENTICATION_FAILED``).
- HTTP 403 maps to :class:`PermissionDeniedError` (``PERMISSION_DENIED``).
- HTTP 429 maps to :class:`RateLimitError` (``RATE_LIMITED``).
- Malformed responses and other failures raise structured errors so the
  execution runtime persists a real failure — availability is never
  fabricated.
- Reads require ``READ_CALENDAR``; event writes require ``WRITE_CALENDAR``
  (a dangerous permission never granted implicitly).
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from app.agents.permissions import Permission
from app.integrations.exceptions import (
    AuthenticationError,
    CapabilityUnavailableError,
    ConnectorError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.google_auth import (
    GoogleOAuthTokenProvider,
    auth_headers,
    decode_error_payload,
)
from app.integrations.http_client import HttpClient, HttpStatusError
from app.integrations.integration_connector import IntegrationConnector

_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
_OAUTH_SCOPE = "https://www.googleapis.com/auth/calendar"

_READ_CAPABILITIES = frozenset(
    {
        "calendar.health",
        "calendar.list_calendars",
        "calendar.list_events",
        "calendar.get_event",
        "calendar.find_free_busy",
    }
)


class GoogleCalendarConnector(IntegrationConnector):
    """Google Calendar connector for calendars and events."""

    required_env_vars: tuple[str, ...] = (
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "GOOGLE_REFRESH_TOKEN",
    )
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        capability: (
            Permission.READ_CALENDAR
            if capability in _READ_CAPABILITIES
            else Permission.WRITE_CALENDAR
        )
        for capability in (
            "calendar.health",
            "calendar.list_calendars",
            "calendar.list_events",
            "calendar.get_event",
            "calendar.create_event",
            "calendar.update_event",
            "calendar.delete_event",
            "calendar.find_free_busy",
        )
    }

    def __init__(
        self,
        client: HttpClient | None = None,
        *,
        token_provider: GoogleOAuthTokenProvider | None = None,
    ) -> None:
        super().__init__(
            name="calendar",
            description="Google Calendar API integration",
        )
        self.client = client or HttpClient()
        self.token_provider = token_provider or GoogleOAuthTokenProvider(
            client=self.client, scope=_OAUTH_SCOPE
        )

    def _capabilities(self) -> tuple[str, ...]:
        return (
            "calendar.health",
            "calendar.list_calendars",
            "calendar.list_events",
            "calendar.get_event",
            "calendar.create_event",
            "calendar.update_event",
            "calendar.delete_event",
            "calendar.find_free_busy",
        )

    def _configuration_status(self) -> tuple[Any, str | None]:
        from app.integrations.connector_health import ConnectorHealthStatus

        missing = self.token_provider.missing_configuration()
        if missing:
            return (
                ConnectorHealthStatus.NOT_CONFIGURED,
                f"missing environment configuration: {', '.join(missing)}",
            )
        return ConnectorHealthStatus.HEALTHY, "configured"

    def _dispatch(self, capability: str, params: dict[str, Any]) -> dict[str, Any]:
        if capability == "calendar.health":
            return self._health()
        if capability == "calendar.list_calendars":
            return self._list_calendars(params)
        if capability == "calendar.list_events":
            return self._list_events(params)
        if capability == "calendar.get_event":
            return self._get_event(params)
        if capability == "calendar.create_event":
            return self._create_event(params)
        if capability == "calendar.update_event":
            return self._update_event(params)
        if capability == "calendar.delete_event":
            return self._delete_event(params)
        if capability == "calendar.find_free_busy":
            return self._free_busy(params)
        raise CapabilityUnavailableError(f"unsupported capability: {capability}")

    # ------------------------------------------------------------------
    # Operations
    # ------------------------------------------------------------------
    def _health(self) -> dict[str, Any]:
        status, message = self._configuration_status()
        return {
            "integration": "calendar",
            "status": status.value,
            "configured": status.value == "Healthy",
            "message": message,
        }

    def _list_calendars(self, params: dict[str, Any]) -> dict[str, Any]:
        query: dict[str, Any] = {"maxResults": int(params.get("max_results") or 50)}
        if params.get("min_access_role"):
            query["minAccessRole"] = params["min_access_role"]
        response = self._fetch(
            "GET", f"{_CALENDAR_API}/users/me/calendarList", params=query
        )
        payload = self._decode(response, path="calendarList")
        items = payload.get("items") or []
        return {
            "total": payload.get("totalItems") or len(items),
            "items": [
                {
                    "id": item.get("id"),
                    "summary": item.get("summary"),
                    "description": item.get("description"),
                    "time_zone": item.get("timeZone"),
                    "access_role": item.get("accessRole"),
                    "primary": bool(item.get("primary")),
                }
                for item in items
                if isinstance(item, dict)
            ],
        }

    def _list_events(self, params: dict[str, Any]) -> dict[str, Any]:
        calendar_id = params.get("calendar_id") or "primary"
        query: dict[str, Any] = {"maxResults": int(params.get("max_results") or 50)}
        if params.get("time_min"):
            query["timeMin"] = params["time_min"]
        if params.get("time_max"):
            query["timeMax"] = params["time_max"]
        if params.get("query"):
            query["q"] = params["query"]
        if params.get("order_by"):
            query["orderBy"] = params["order_by"]
        if params.get("single_events") is not None:
            query["singleEvents"] = bool(params["single_events"])
        response = self._fetch(
            "GET", f"{_CALENDAR_API}/calendars/{self._quote(calendar_id)}/events", params=query
        )
        payload = self._decode(response, path=f"calendars/{calendar_id}/events")
        items = payload.get("items") or []
        return {
            "calendar_id": calendar_id,
            "total": payload.get("totalItems") or len(items),
            "items": [item for item in items if isinstance(item, dict)],
        }

    def _get_event(self, params: dict[str, Any]) -> dict[str, Any]:
        calendar_id = params.get("calendar_id") or "primary"
        event_id = params.get("event_id")
        if not event_id:
            raise ValueError("event_id is required for calendar.get_event")
        response = self._fetch(
            "GET",
            f"{_CALENDAR_API}/calendars/{self._quote(calendar_id)}/events/{self._quote(event_id)}",
        )
        payload = self._decode(response, path=f"events/{event_id}")
        return {"calendar_id": calendar_id, "event": payload}

    def _create_event(self, params: dict[str, Any]) -> dict[str, Any]:
        calendar_id = params.get("calendar_id") or "primary"
        event = self._build_event(params)
        response = self._fetch(
            "POST",
            f"{_CALENDAR_API}/calendars/{self._quote(calendar_id)}/events",
            headers={"Content-Type": "application/json"},
            body=json.dumps(event).encode(),
        )
        payload = self._decode(response, path=f"calendars/{calendar_id}/events")
        return {"calendar_id": calendar_id, "created": True, "event": payload}

    def _update_event(self, params: dict[str, Any]) -> dict[str, Any]:
        calendar_id = params.get("calendar_id") or "primary"
        event_id = params.get("event_id")
        if not event_id:
            raise ValueError("event_id is required for calendar.update_event")
        event = self._build_event(params)
        response = self._fetch(
            "PATCH",
            f"{_CALENDAR_API}/calendars/{self._quote(calendar_id)}/events/{self._quote(event_id)}",
            headers={"Content-Type": "application/json"},
            body=json.dumps(event).encode(),
        )
        payload = self._decode(response, path=f"events/{event_id}")
        return {"calendar_id": calendar_id, "updated": True, "event": payload}

    def _delete_event(self, params: dict[str, Any]) -> dict[str, Any]:
        calendar_id = params.get("calendar_id") or "primary"
        event_id = params.get("event_id")
        if not event_id:
            raise ValueError("event_id is required for calendar.delete_event")
        response = self._fetch(
            "DELETE",
            f"{_CALENDAR_API}/calendars/{self._quote(calendar_id)}/events/{self._quote(event_id)}",
        )
        self._decode(response, path=f"events/{event_id}", allow_empty=True)
        return {"calendar_id": calendar_id, "deleted": True, "event_id": event_id}

    def _free_busy(self, params: dict[str, Any]) -> dict[str, Any]:
        time_min = params.get("time_min") or params.get("start")
        time_max = params.get("time_max") or params.get("end")
        if not time_min or not time_max:
            raise ValueError("time_min and time_max are required for calendar.find_free_busy")
        payload: dict[str, Any] = {
            "timeMin": time_min,
            "timeMax": time_max,
            "items": [{"id": params.get("calendar_id") or "primary"}],
        }
        if params.get("time_zone"):
            payload["timeZone"] = params["time_zone"]
        response = self._fetch(
            "POST",
            f"{_CALENDAR_API}/freeBusy",
            headers={"Content-Type": "application/json"},
            body=json.dumps(payload).encode(),
        )
        decoded = self._decode(response, path="freeBusy")
        calendars = decoded.get("calendars") or {}
        calendar_id = payload["items"][0]["id"]
        busy = (calendars.get(calendar_id) or {}).get("busy") or []
        return {"calendar_id": calendar_id, "time_min": time_min, "time_max": time_max, "busy": busy}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _build_event(params: dict[str, Any]) -> dict[str, Any]:
        """Build a Calendar API event payload from structured parameters."""
        event: dict[str, Any] = {}
        for key, api_key in (
            ("summary", "summary"),
            ("description", "description"),
            ("location", "location"),
            ("status", "status"),
        ):
            if params.get(key):
                event[api_key] = params[key]
        if params.get("start"):
            event["start"] = GoogleCalendarConnector._time_value(params["start"])
        if params.get("end"):
            event["end"] = GoogleCalendarConnector._time_value(params["end"])
        if params.get("attendees"):
            attendees = params["attendees"]
            if isinstance(attendees, list):
                event["attendees"] = [
                    {"email": email} if isinstance(email, str) else email for email in attendees
                ]
        if params.get("reminders"):
            event["reminders"] = params["reminders"]
        if params.get("time_zone") and "start" in event and isinstance(event["start"], dict):
            event["start"].setdefault("timeZone", params["time_zone"])
            if "end" in event and isinstance(event["end"], dict):
                event["end"].setdefault("timeZone", params["time_zone"])
        return event

    @staticmethod
    def _time_value(value: Any) -> dict[str, Any]:
        """Normalize an ISO string or mapping into a Calendar time object."""
        if isinstance(value, dict):
            return dict(value)
        return {"dateTime": str(value)}

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
        request_headers = {**auth_headers(self.token_provider), **(headers or {})}
        try:
            return self.client.fetch(
                url, method=method, headers=request_headers, body=body, params=params
            )
        except HttpStatusError as exc:
            status = int(exc.status)
            if status == 401:
                raise AuthenticationError(
                    f"AUTHENTICATION_FAILED: Google Calendar returned HTTP 401 "
                    f"at {exc.url} (refresh token invalid or expired)"
                ) from exc
            if status == 403:
                raise PermissionDeniedError(
                    f"PERMISSION_DENIED: Google Calendar returned HTTP 403 at "
                    f"{exc.url} (insufficient OAuth scope or permissions)"
                ) from exc
            if status == 429:
                raise RateLimitError(
                    f"RATE_LIMITED: Google Calendar returned HTTP 429 at {exc.url}"
                ) from exc
            raise ConnectorError(
                f"Google Calendar API error: HTTP {status} at {exc.url}"
            ) from exc

    def _decode(self, response: Any, *, path: str, allow_empty: bool = False) -> dict[str, Any]:
        """Parse a Calendar API response, mapping failures to distinct errors."""
        status = int(getattr(response, "status", 200) or 200)
        if status == 401:
            raise AuthenticationError(
                f"AUTHENTICATION_FAILED: Google Calendar returned HTTP 401 at {path}"
            )
        if status == 403:
            raise PermissionDeniedError(
                f"PERMISSION_DENIED: Google Calendar returned HTTP 403 at {path} "
                f"(insufficient OAuth scope or permissions)"
            )
        if status == 429:
            raise RateLimitError(f"RATE_LIMITED: Google Calendar returned HTTP 429 at {path}")
        if status >= 400:
            raise ConnectorError(
                f"Google Calendar API error: HTTP {status} at {path}: "
                f"{decode_error_payload(response.text)}"
            )
        if allow_empty and not response.text.strip():
            return {}
        try:
            payload = json.loads(response.text)
        except (json.JSONDecodeError, TypeError) as exc:
            raise ConnectorError(
                f"invalid response from Google Calendar at {path}: "
                "response body is not valid JSON"
            ) from exc
        if not isinstance(payload, dict):
            raise ConnectorError(
                f"invalid response from Google Calendar at {path}: "
                "expected a JSON object"
            )
        return payload

    @staticmethod
    def _quote(value: str) -> str:
        """URL-quote a path segment (calendar/event ids)."""
        from urllib.parse import quote

        return quote(str(value), safe="")
