"""Shared hermetic Google API transport helpers for connector tests.

A fake ``urlopen`` serves fixture responses for the Google OAuth, Calendar,
and Drive connectors so the REAL request pipelines execute end to end
without touching the network. No credentials or external calls exist here.
"""

from __future__ import annotations

import json
from typing import Any

from tests.integration_helpers import FakeResponse


class FakeGoogleToken:
    """Duck-typed GoogleOAuthTokenProvider that never touches the network."""

    def __init__(self, configured: bool = True) -> None:
        self._configured = configured
        self.calls = 0

    @property
    def is_configured(self) -> bool:
        return self._configured

    def missing_configuration(self) -> tuple[str, ...]:
        return () if self._configured else ("GOOGLE_CLIENT_ID", "GOOGLE_REFRESH_TOKEN")

    def get_token(self) -> str:
        self.calls += 1
        if not self._configured:
            from app.integrations.exceptions import AuthenticationError

            raise AuthenticationError("AUTHENTICATION_FAILED: Google OAuth credentials are not configured")
        return "fake-access-token"

    def invalidate(self) -> None:
        self.calls = 0

    scope = ""


class GoogleFakeOpener:
    """Serve JSON (or bytes) responses keyed by (method, URL suffix).

    ``responses`` maps ``(method, suffix)`` to a payload dict/bytes. A
    payload may be a ``(status, payload)`` tuple to control the HTTP status.
    Unmatched requests fall back to ``default_status``/``default_payload``.
    """

    def __init__(
        self,
        responses: dict[tuple[str, str], Any] | None = None,
        *,
        default_status: int = 200,
        default_payload: Any = None,
    ) -> None:
        self.responses = responses or {}
        self.default_status = default_status
        self.default_payload = default_payload
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request: Any, timeout: float | None = None) -> FakeResponse:
        url = str(getattr(request, "full_url", request))
        method = str(getattr(request, "get_method", lambda: "GET")())
        self.calls.append((method, url))
        # Among matching (method, suffix) routes prefer the one whose suffix
        # appears latest in the URL (query-string routes beat shared paths)
        # and, among ties, the longest suffix.
        candidates: list[tuple[int, int, Any]] = []
        for (route_method, suffix), routed in self.responses.items():
            if route_method == method and suffix in url:
                candidates.append((url.rindex(suffix), len(suffix), routed))
        payload: Any = None
        status: int | None = None
        if candidates:
            _, _, routed = max(candidates, key=lambda item: (item[0], item[1]))
            if isinstance(routed, tuple) and len(routed) == 2 and isinstance(routed[0], int):
                status, payload = routed
            else:
                payload = routed
        if payload is None:
            payload = self.default_payload
        if status is None:
            status = self.default_status
        if isinstance(payload, bytes):
            body = payload
            content_type = "application/octet-stream"
        elif payload is None:
            body = b""
            content_type = "application/json"
        else:
            body = json.dumps(payload).encode()
            content_type = "application/json"
        return FakeResponse(body, url, status=status, content_type=content_type)
