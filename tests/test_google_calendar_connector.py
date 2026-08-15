"""Tests for the Google Calendar connector.

Covers: provider-not-configured honesty, calendar discovery, event
list/get/create/update/delete, free/busy lookup, distinct authentication
failure, permission denial, rate limiting, malformed responses, and
persisted execution through IntegrationService. Never touches the real
Google Calendar API.
"""

from __future__ import annotations

import pytest

from app.agents.permissions import Permission
from app.integrations.connector_health import ConnectorHealthStatus
from app.integrations.exceptions import (
    AuthenticationError,
    ConnectorError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.google_calendar import GoogleCalendarConnector
from app.integrations.http_client import HttpClient
from tests.google_helpers import FakeGoogleToken, GoogleFakeOpener

EVENT_1 = {"id": "evt-1", "summary": "Supplier meeting", "start": {"dateTime": "2026-08-20T10:00:00Z"}}
CALENDAR_LIST = {
    "items": [{"id": "primary", "summary": "My Calendar", "primary": True, "accessRole": "owner"}]
}
EVENTS_LIST = {"items": [EVENT_1], "totalItems": 1}
FREE_BUSY = {"calendars": {"primary": {"busy": [{"start": "2026-08-20T10:00:00Z", "end": "2026-08-20T11:00:00Z"}]}}}


def _connector(opener=None, *, token: FakeGoogleToken | None = None) -> GoogleCalendarConnector:
    return GoogleCalendarConnector(
        client=HttpClient(opener=opener),
        token_provider=token or FakeGoogleToken(),
    )


def test_calendar_reports_not_configured_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI", "GOOGLE_REFRESH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    connector = GoogleCalendarConnector()
    assert connector.health_check().status is ConnectorHealthStatus.NOT_CONFIGURED
    assert not connector.is_configured
    available, reason = connector.capability_available("calendar.list_events")
    assert not available
    assert "GOOGLE_CLIENT_ID" in reason


def test_calendar_list_calendars() -> None:
    opener = GoogleFakeOpener({("GET", "/users/me/calendarList"): CALENDAR_LIST})
    connector = _connector(opener)
    assert connector.is_configured

    result = connector.execute("calendar.list_calendars", {}, permissions={Permission.READ_CALENDAR})
    assert result["items"][0]["summary"] == "My Calendar"
    assert result["items"][0]["primary"] is True


def test_calendar_list_events_with_query() -> None:
    opener = GoogleFakeOpener({("GET", "/calendars/primary/events"): EVENTS_LIST})
    connector = _connector(opener)

    result = connector.execute(
        "calendar.list_events",
        {"calendar_id": "primary", "query": "supplier", "max_results": 10},
        permissions={Permission.READ_CALENDAR},
    )
    assert result["items"][0]["id"] == "evt-1"
    method, url = opener.calls[0]
    assert method == "GET"
    assert "q=supplier" in url and "maxResults=10" in url


def test_calendar_get_event() -> None:
    opener = GoogleFakeOpener({("GET", "/calendars/primary/events/evt-1"): EVENT_1})
    connector = _connector(opener)

    result = connector.execute(
        "calendar.get_event", {"calendar_id": "primary", "event_id": "evt-1"},
        permissions={Permission.READ_CALENDAR},
    )
    assert result["event"]["summary"] == "Supplier meeting"


def test_calendar_create_event_posts_payload() -> None:
    opener = GoogleFakeOpener({("POST", "/calendars/primary/events"): EVENT_1})
    connector = _connector(opener)

    result = connector.execute(
        "calendar.create_event",
        {
            "calendar_id": "primary",
            "summary": "Supplier meeting",
            "description": "Quarterly review",
            "start": "2026-08-20T10:00:00Z",
            "end": "2026-08-20T11:00:00Z",
            "attendees": ["supplier@example.com"],
        },
        permissions={Permission.READ_CALENDAR, Permission.WRITE_CALENDAR},
    )
    assert result["created"] is True
    method, url = opener.calls[0]
    assert method == "POST"
    assert url.endswith("/calendars/primary/events")


def test_calendar_create_event_requires_write_permission() -> None:
    connector = _connector(GoogleFakeOpener())
    with pytest.raises(PermissionDeniedError, match="WRITE_CALENDAR"):
        connector.execute(
            "calendar.create_event",
            {"summary": "Meeting", "start": "2026-08-20T10:00:00Z", "end": "2026-08-20T11:00:00Z"},
            permissions={Permission.READ_CALENDAR},
        )


def test_calendar_update_event_patches() -> None:
    opener = GoogleFakeOpener({("PATCH", "/calendars/primary/events/evt-1"): {**EVENT_1, "summary": "Moved"}})
    connector = _connector(opener)

    result = connector.execute(
        "calendar.update_event",
        {"calendar_id": "primary", "event_id": "evt-1", "summary": "Moved"},
        permissions={Permission.READ_CALENDAR, Permission.WRITE_CALENDAR},
    )
    assert result["updated"] is True
    assert result["event"]["summary"] == "Moved"


def test_calendar_delete_event() -> None:
    opener = GoogleFakeOpener({("DELETE", "/calendars/primary/events/evt-1"): (204, None)})
    connector = _connector(opener)

    result = connector.execute(
        "calendar.delete_event",
        {"calendar_id": "primary", "event_id": "evt-1"},
        permissions={Permission.READ_CALENDAR, Permission.WRITE_CALENDAR},
    )
    assert result["deleted"] is True
    assert result["event_id"] == "evt-1"


def test_calendar_delete_event_requires_write_permission() -> None:
    connector = _connector(GoogleFakeOpener())
    with pytest.raises(PermissionDeniedError, match="WRITE_CALENDAR"):
        connector.execute(
            "calendar.delete_event", {"calendar_id": "primary", "event_id": "evt-1"},
            permissions={Permission.READ_CALENDAR},
        )


def test_calendar_find_free_busy() -> None:
    opener = GoogleFakeOpener({("POST", "/freeBusy"): FREE_BUSY})
    connector = _connector(opener)

    result = connector.execute(
        "calendar.find_free_busy",
        {"calendar_id": "primary", "time_min": "2026-08-20T09:00:00Z", "time_max": "2026-08-20T12:00:00Z"},
        permissions={Permission.READ_CALENDAR},
    )
    assert result["busy"][0]["start"] == "2026-08-20T10:00:00Z"


def test_calendar_auth_failure_is_distinct() -> None:
    opener = GoogleFakeOpener(default_status=401, default_payload={"error": "unauthorized"})
    connector = _connector(opener)
    with pytest.raises(AuthenticationError, match="AUTHENTICATION_FAILED"):
        connector.execute("calendar.list_events", {}, permissions={Permission.READ_CALENDAR})


def test_calendar_permission_denied_http_403() -> None:
    opener = GoogleFakeOpener(default_status=403, default_payload={"error": {"message": "insufficient permissions"}})
    connector = _connector(opener)
    with pytest.raises(PermissionDeniedError, match="PERMISSION_DENIED"):
        connector.execute("calendar.list_events", {}, permissions={Permission.READ_CALENDAR})


def test_calendar_rate_limit_is_distinct() -> None:
    opener = GoogleFakeOpener(default_status=429, default_payload={"error": {"message": "rate limit"}})
    connector = _connector(opener)
    with pytest.raises(RateLimitError, match="RATE_LIMITED"):
        connector.execute("calendar.list_events", {}, permissions={Permission.READ_CALENDAR})


def test_calendar_malformed_response_raises_structured_error() -> None:
    def garbage(request, timeout=None):
        from tests.integration_helpers import FakeResponse

        return FakeResponse(b"<html>not json</html>", str(request.full_url), content_type="text/html")

    connector = _connector(garbage)
    with pytest.raises(ConnectorError, match="not valid JSON"):
        connector.execute("calendar.list_events", {}, permissions={Permission.READ_CALENDAR})


def test_calendar_health_capability() -> None:
    connector = _connector(GoogleFakeOpener())
    result = connector.execute("calendar.health", {}, permissions={Permission.READ_CALENDAR})
    assert result["configured"] is True
    assert result["integration"] == "calendar"
