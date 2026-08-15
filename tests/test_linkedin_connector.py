"""Tests for the LinkedIn connector.

Covers: provider-not-configured honesty, organization metadata, text post
creation, post retrieval, post deletion, distinct authentication failure,
permission denial (publishing requires PUBLISH_SOCIAL), rate limiting, and
malformed responses. Never touches the real LinkedIn API and never
publishes anything.
"""

from __future__ import annotations

import json

import pytest

from app.agents.permissions import Permission
from app.integrations.connector_health import ConnectorHealthStatus
from app.integrations.exceptions import (
    AuthenticationError,
    ConnectorError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.http_client import HttpClient
from app.integrations.linkedin import LinkedInConnector
from tests.integration_helpers import FakeResponse

ORGANIZATION = {
    "id": "urn:li:organization:12345",
    "name": "Organigram",
    "localizedName": "Organigram",
}


def _opener(responses=None, *, default_status: int = 200, default_payload=None):
    routes = responses or {}
    call_log: list[tuple[str, str]] = []

    def opener(request, timeout=None) -> FakeResponse:
        url = str(getattr(request, "full_url", request))
        method = str(getattr(request, "get_method", lambda: "GET")())
        call_log.append((method, url))
        payload = None
        status = None
        for (route_method, suffix), routed in routes.items():
            if route_method == method and suffix in url:
                if isinstance(routed, tuple) and len(routed) == 2 and isinstance(routed[0], int):
                    status, payload = routed
                else:
                    payload = routed
                break
        if payload is None:
            payload = default_payload
        if status is None:
            status = default_status
        body = b"" if payload is None else json.dumps(payload).encode()
        return FakeResponse(body, url, status=status, content_type="application/json")

    opener.calls = call_log
    return opener


def _connector(opener, *, token: str = "test-token", org_id: str = "12345") -> LinkedInConnector:
    return LinkedInConnector(
        client=HttpClient(opener=opener),
        access_token=token,
        organization_id=org_id,
    )


def test_linkedin_reports_not_configured_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LINKEDIN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("LINKEDIN_ORGANIZATION_ID", raising=False)
    connector = LinkedInConnector()
    assert connector.health_check().status is ConnectorHealthStatus.NOT_CONFIGURED
    assert not connector.is_configured
    available, reason = connector.capability_available("linkedin.get_organization")
    assert not available
    assert "LINKEDIN_ACCESS_TOKEN" in reason and "LINKEDIN_ORGANIZATION_ID" in reason


def test_linkedin_get_organization() -> None:
    opener = _opener({("GET", "/organizations/12345"): ORGANIZATION})
    connector = _connector(opener)

    result = connector.execute(
        "linkedin.get_organization", {}, permissions={Permission.READ_SOCIAL}
    )
    assert result["organization"]["name"] == "Organigram"
    method, url = opener.calls[0]
    assert method == "GET"
    assert url.endswith("/rest/organizations/12345")


def test_linkedin_create_text_post_posts_commentary() -> None:
    created = {"id": "urn:li:post:999", "author": "urn:li:organization:12345"}
    opener = _opener({("POST", "/posts"): (201, created)})
    connector = _connector(opener)

    result = connector.execute(
        "linkedin.create_text_post",
        {"commentary": "Our quarterly results are live."},
        permissions={Permission.READ_SOCIAL, Permission.PUBLISH_SOCIAL},
    )
    assert result["created"] is True
    assert result["post_id"] == "999"
    assert result["urn"] == "urn:li:post:999"
    method, url = opener.calls[0]
    assert method == "POST"
    assert url.endswith("/rest/posts")


def test_linkedin_create_text_post_requires_publish_permission() -> None:
    connector = _connector(_opener())
    with pytest.raises(PermissionDeniedError, match="PUBLISH_SOCIAL"):
        connector.execute(
            "linkedin.create_text_post",
            {"commentary": "hello"},
            permissions={Permission.READ_SOCIAL},
        )


def test_linkedin_get_post_normalizes_urn() -> None:
    post = {"id": "urn:li:post:999", "commentary": "hello", "author": "urn:li:organization:12345"}
    opener = _opener({("GET", "/posts/999"): post})
    connector = _connector(opener)

    result = connector.execute(
        "linkedin.get_post", {"post_id": "urn:li:post:999"}, permissions={Permission.READ_SOCIAL}
    )
    assert result["post_id"] == "999"
    assert result["post"]["commentary"] == "hello"


def test_linkedin_delete_post() -> None:
    opener = _opener({("DELETE", "/posts/999"): (204, None)})
    connector = _connector(opener)

    result = connector.execute(
        "linkedin.delete_post",
        {"post_id": "urn:li:post:999"},
        permissions={Permission.READ_SOCIAL, Permission.PUBLISH_SOCIAL},
    )
    assert result["deleted"] is True
    method, url = opener.calls[0]
    assert method == "DELETE"
    assert url.endswith("/rest/posts/999")


def test_linkedin_auth_failure_is_distinct() -> None:
    opener = _opener(default_status=401, default_payload={"message": "unauthorized"})
    connector = _connector(opener)
    with pytest.raises(AuthenticationError, match="AUTHENTICATION_FAILED"):
        connector.execute("linkedin.get_organization", {}, permissions={Permission.READ_SOCIAL})


def test_linkedin_authorization_failure_is_permission_denied() -> None:
    opener = _opener(default_status=403, default_payload={"message": "forbidden"})
    connector = _connector(opener)
    with pytest.raises(PermissionDeniedError, match="PERMISSION_DENIED"):
        connector.execute("linkedin.get_organization", {}, permissions={Permission.READ_SOCIAL})


def test_linkedin_rate_limit_is_distinct() -> None:
    opener = _opener(default_status=429, default_payload={"message": "rate limit"})
    connector = _connector(opener)
    with pytest.raises(RateLimitError, match="RATE_LIMITED"):
        connector.execute("linkedin.get_organization", {}, permissions={Permission.READ_SOCIAL})


def test_linkedin_malformed_response_raises_structured_error() -> None:
    def garbage(request, timeout=None) -> FakeResponse:
        return FakeResponse(b"<html>not json</html>", str(request.full_url), content_type="text/html")

    connector = _connector(garbage)
    with pytest.raises(ConnectorError, match="not valid JSON"):
        connector.execute("linkedin.get_organization", {}, permissions={Permission.READ_SOCIAL})


def test_linkedin_health_capability() -> None:
    connector = _connector(_opener())
    result = connector.execute("linkedin.health", {}, permissions={Permission.READ_SOCIAL})
    assert result["configured"] is True
    assert result["integration"] == "linkedin"
