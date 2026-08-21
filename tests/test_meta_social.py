"""Tests for the Meta Social Connector and Social facade.

Covers: configuration validation, page discovery, Instagram account discovery,
page info, post publishing, post retrieval, post deletion, page insights,
post insights, capability reporting, provider delegation, error handling,
and token security. Never touches the real Meta Graph API.
"""

from __future__ import annotations

import json

import pytest

from app.agents.permissions import Permission
from app.integrations.connector_health import ConnectorHealthStatus
from app.integrations.exceptions import (
    AuthenticationError,
    CapabilityUnavailableError,
    ConnectorError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.http_client import HttpClient
from app.integrations.meta_social import MetaSocialConnector
from app.integrations.social import SocialConnector
from tests.integration_helpers import FakeResponse


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

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


def _connector(opener, *, token: str = "test-page-token") -> MetaSocialConnector:
    return MetaSocialConnector(
        client=HttpClient(opener=opener),
        page_access_token=token,
    )


# ------------------------------------------------------------------
# MetaSocialConnector tests
# ------------------------------------------------------------------

def test_meta_social_reports_not_configured_without_token() -> None:
    connector = MetaSocialConnector()
    assert connector.health_check().status is ConnectorHealthStatus.NOT_CONFIGURED
    assert not connector.is_configured


def test_meta_social_health_when_configured() -> None:
    connector = _connector(_opener())
    result = connector.execute(
        "meta_social.health", {}, permissions={Permission.READ_SOCIAL}
    )
    assert result["configured"] is True
    assert result["integration"] == "meta_social"


def test_meta_social_list_pages() -> None:
    pages_data = {
        "data": [
            {"id": "111", "name": "My Page", "category": "Business", "fan_count": 1200},
            {"id": "222", "name": "另一Page", "category": "Music", "fan_count": 500},
        ]
    }
    opener = _opener({("GET", "/me/accounts"): pages_data})
    connector = _connector(opener)

    result = connector.execute(
        "meta_social.list_pages", {}, permissions={Permission.READ_SOCIAL}
    )
    assert result["total"] == 2
    assert result["pages"][0]["page_id"] == "111"
    assert result["pages"][0]["name"] == "My Page"
    assert result["pages"][1]["fan_count"] == 500


def test_meta_social_list_pages_empty() -> None:
    opener = _opener({("GET", "/me/accounts"): {"data": []}})
    connector = _connector(opener)

    result = connector.execute(
        "meta_social.list_pages", {}, permissions={Permission.READ_SOCIAL}
    )
    assert result["total"] == 0
    assert result["pages"] == []


def test_meta_social_list_instagram_accounts() -> None:
    page_data = {
        "instagram_business_account": {
            "id": "ig_999",
            "username": "mybrand",
            "name": "My Brand",
            "followers_count": 5000,
        }
    }
    opener = _opener({("GET", "/111"): page_data})
    connector = _connector(opener)

    result = connector.execute(
        "meta_social.list_instagram_accounts",
        {"page_id": "111"},
        permissions={Permission.READ_SOCIAL},
    )
    assert result["instagram_account"]["account_id"] == "ig_999"
    assert result["instagram_account"]["username"] == "mybrand"


def test_meta_social_list_instagram_accounts_none_linked() -> None:
    opener = _opener({("GET", "/111"): {}})
    connector = _connector(opener)

    result = connector.execute(
        "meta_social.list_instagram_accounts",
        {"page_id": "111"},
        permissions={Permission.READ_SOCIAL},
    )
    assert result["instagram_account"] is None
    assert "No Instagram" in result["message"]


def test_meta_social_list_instagram_accounts_requires_page_id() -> None:
    connector = _connector(_opener())
    with pytest.raises(ValueError, match="page_id is required"):
        connector.execute(
            "meta_social.list_instagram_accounts",
            {},
            permissions={Permission.READ_SOCIAL},
        )


def test_meta_social_get_page_info() -> None:
    page_data = {"id": "111", "name": "My Page", "about": "We sell things", "fan_count": 1200}
    opener = _opener({("GET", "/111"): page_data})
    connector = _connector(opener)

    result = connector.execute(
        "meta_social.get_page_info",
        {"page_id": "111"},
        permissions={Permission.READ_SOCIAL},
    )
    assert result["page"]["name"] == "My Page"
    assert result["page"]["fan_count"] == 1200


def test_meta_social_get_page_info_requires_page_id() -> None:
    connector = _connector(_opener())
    with pytest.raises(ValueError, match="page_id is required"):
        connector.execute(
            "meta_social.get_page_info",
            {},
            permissions={Permission.READ_SOCIAL},
        )


def test_meta_social_get_post() -> None:
    post_data = {
        "id": "post_123",
        "message": "Hello world!",
        "created_time": "2026-08-21T10:00:00+0000",
        "type": "status",
        "permalink_url": "https://facebook.com/post_123",
        "shares": {"count": 5},
        "likes": {"summary": {"total_count": 42}},
        "comments": {"summary": {"total_count": 10}},
    }
    opener = _opener({("GET", "/post_123"): post_data})
    connector = _connector(opener)

    result = connector.execute(
        "meta_social.get_post",
        {"post_id": "post_123"},
        permissions={Permission.READ_SOCIAL},
    )
    assert result["post_id"] == "post_123"
    assert result["message"] == "Hello world!"
    assert result["shares"] == 5
    assert result["likes"] == 42
    assert result["comments"] == 10


def test_meta_social_get_post_requires_post_id() -> None:
    connector = _connector(_opener())
    with pytest.raises(ValueError, match="post_id is required"):
        connector.execute(
            "meta_social.get_post",
            {},
            permissions={Permission.READ_SOCIAL},
        )


def test_meta_social_publish_post() -> None:
    created = {"id": "post_456"}
    opener = _opener({("POST", "/111/feed"): (200, created)})
    connector = _connector(opener)

    result = connector.execute(
        "meta_social.publish_post",
        {"page_id": "111", "message": "Check out our new product!"},
        permissions={Permission.READ_SOCIAL, Permission.PUBLISH_SOCIAL},
    )
    assert result["created"] is True
    assert result["post_id"] == "post_456"
    assert "post_456" in result["platform_url"]


def test_meta_social_publish_post_with_link() -> None:
    created = {"id": "post_789"}
    opener = _opener({("POST", "/111/feed"): (200, created)})
    connector = _connector(opener)

    result = connector.execute(
        "meta_social.publish_post",
        {
            "page_id": "111",
            "message": "Read our blog",
            "link": "https://example.com/blog",
        },
        permissions={Permission.READ_SOCIAL, Permission.PUBLISH_SOCIAL},
    )
    assert result["created"] is True


def test_meta_social_publish_post_requires_page_id() -> None:
    connector = _connector(_opener())
    with pytest.raises(ValueError, match="page_id is required"):
        connector.execute(
            "meta_social.publish_post",
            {"message": "hello"},
            permissions={Permission.READ_SOCIAL, Permission.PUBLISH_SOCIAL},
        )


def test_meta_social_publish_post_requires_message() -> None:
    connector = _connector(_opener())
    with pytest.raises(ValueError, match="message is required"):
        connector.execute(
            "meta_social.publish_post",
            {"page_id": "111"},
            permissions={Permission.READ_SOCIAL, Permission.PUBLISH_SOCIAL},
        )


def test_meta_social_publish_post_requires_publish_permission() -> None:
    connector = _connector(_opener())
    with pytest.raises(PermissionDeniedError, match="PUBLISH_SOCIAL"):
        connector.execute(
            "meta_social.publish_post",
            {"page_id": "111", "message": "hello"},
            permissions={Permission.READ_SOCIAL},
        )


def test_meta_social_delete_post() -> None:
    opener = _opener({("DELETE", "/post_123"): (200, {"success": True})})
    connector = _connector(opener)

    result = connector.execute(
        "meta_social.delete_post",
        {"post_id": "post_123"},
        permissions={Permission.READ_SOCIAL, Permission.PUBLISH_SOCIAL},
    )
    assert result["deleted"] is True
    assert result["post_id"] == "post_123"


def test_meta_social_get_page_insights() -> None:
    insights = {
        "data": [
            {
                "name": "page_impressions",
                "period": "day",
                "values": [{"value": 1500, "title": "Daily"}, {"value": 2000, "title": "Daily"}],
            },
            {
                "name": "page_engaged_users",
                "period": "day",
                "values": [{"value": 300}],
            },
        ]
    }
    opener = _opener({("GET", "/111/insights"): insights})
    connector = _connector(opener)

    result = connector.execute(
        "meta_social.get_page_insights",
        {"page_id": "111"},
        permissions={Permission.READ_SOCIAL},
    )
    assert result["page_id"] == "111"
    assert result["summary"]["page_impressions"] == 3500
    assert result["summary"]["page_engaged_users"] == 300


def test_meta_social_get_post_insights() -> None:
    insights = {
        "data": [
            {"name": "post_impressions", "values": [{"value": 500}]},
            {"name": "post_engagements", "values": [{"value": 45}]},
        ]
    }
    opener = _opener({("GET", "/post_123/insights"): insights})
    connector = _connector(opener)

    result = connector.execute(
        "meta_social.get_post_insights",
        {"post_id": "post_123"},
        permissions={Permission.READ_SOCIAL},
    )
    assert result["post_id"] == "post_123"
    assert result["summary"]["post_impressions"] == 500
    assert result["summary"]["post_engagements"] == 45


def test_meta_social_unsupported_capability() -> None:
    connector = _connector(_opener())
    with pytest.raises(CapabilityUnavailableError, match="not supported"):
        connector.execute(
            "meta_social.nonexistent", {}, permissions={Permission.READ_SOCIAL}
        )


# ------------------------------------------------------------------
# Error handling
# ------------------------------------------------------------------

def test_meta_social_auth_error() -> None:
    opener = _opener(default_status=401, default_payload={"error": {"message": "unauthorized"}})
    connector = _connector(opener)
    with pytest.raises(AuthenticationError, match="AUTHENTICATION_FAILED"):
        connector.execute(
            "meta_social.list_pages", {}, permissions={Permission.READ_SOCIAL}
        )


def test_meta_social_permission_denied() -> None:
    opener = _opener(default_status=403, default_payload={"error": {"message": "forbidden"}})
    connector = _connector(opener)
    with pytest.raises(PermissionDeniedError, match="PERMISSION_DENIED"):
        connector.execute(
            "meta_social.list_pages", {}, permissions={Permission.READ_SOCIAL}
        )


def test_meta_social_rate_limit() -> None:
    opener = _opener(default_status=429, default_payload={"error": {"message": "rate limit"}})
    connector = _connector(opener)
    with pytest.raises(RateLimitError, match="RATE_LIMITED"):
        connector.execute(
            "meta_social.list_pages", {}, permissions={Permission.READ_SOCIAL}
        )


def test_meta_social_api_error_in_200_response() -> None:
    """Meta sometimes returns errors in 200 responses."""
    error_payload = {
        "error": {
            "message": "Invalid token",
            "code": 190,
            "type": "OAuthException",
        }
    }
    opener = _opener(default_status=200, default_payload=error_payload)
    connector = _connector(opener)
    with pytest.raises(AuthenticationError, match="token error 190"):
        connector.execute(
            "meta_social.list_pages", {}, permissions={Permission.READ_SOCIAL}
        )


def test_meta_social_malformed_json() -> None:
    def garbage(request, timeout=None) -> FakeResponse:
        return FakeResponse(b"<html>not json</html>", str(request.full_url), content_type="text/html")

    connector = _connector(garbage)
    with pytest.raises(ConnectorError, match="not valid JSON"):
        connector.execute(
            "meta_social.list_pages", {}, permissions={Permission.READ_SOCIAL}
        )


def test_meta_social_token_not_exposed_in_error() -> None:
    """Access token must never appear in error messages."""
    opener = _opener(default_status=401, default_payload={"error": {"message": "unauthorized"}})
    connector = _connector(opener, token="super-secret-token-xyz")
    with pytest.raises(AuthenticationError) as exc_info:
        connector.execute(
            "meta_social.list_pages", {}, permissions={Permission.READ_SOCIAL}
        )
    assert "super-secret-token-xyz" not in str(exc_info.value)


# ------------------------------------------------------------------
# Capability permissions
# ------------------------------------------------------------------

def test_meta_social_capability_permissions_declared() -> None:
    connector = MetaSocialConnector()
    perms = connector.CAPABILITY_PERMISSIONS
    # Read capabilities
    for cap in ("meta_social.health", "meta_social.list_pages", "meta_social.get_post"):
        assert perms[cap] is Permission.READ_SOCIAL
    # Write capabilities
    for cap in ("meta_social.publish_post", "meta_social.delete_post"):
        assert perms[cap] is Permission.PUBLISH_SOCIAL


def test_meta_social_capabilities_list() -> None:
    connector = MetaSocialConnector()
    caps = connector.get_capabilities()
    assert "meta_social.health" in caps
    assert "meta_social.list_pages" in caps
    assert "meta_social.publish_post" in caps
    assert "meta_social.get_page_insights" in caps


# ------------------------------------------------------------------
# SocialConnector facade tests
# ------------------------------------------------------------------

def test_social_connector_reports_not_configured_without_providers() -> None:
    connector = SocialConnector()
    assert connector.health_check().status is ConnectorHealthStatus.NOT_CONFIGURED


def test_social_connector_register_provider() -> None:
    social = SocialConnector()
    meta = MetaSocialConnector(
        client=HttpClient(opener=_opener()),
        page_access_token="test-token",
    )
    social.register_provider("meta", meta)

    assert social.get_provider("meta") is meta
    assert social.get_provider("linkedin") is None


def test_social_connector_list_providers() -> None:
    social = SocialConnector()
    meta = MetaSocialConnector(
        client=HttpClient(opener=_opener()),
        page_access_token="test-token",
    )
    social.register_provider("meta", meta)

    providers = social.list_providers()
    assert providers["meta"]["configured"] is True
    assert providers["meta"]["registered"] is True
    assert providers["linkedin"]["registered"] is False


def test_social_connector_delegates_to_provider() -> None:
    pages_data = {"data": [{"id": "111", "name": "Test Page"}]}
    opener = _opener({("GET", "/me/accounts"): pages_data})

    social = SocialConnector()
    meta = MetaSocialConnector(
        client=HttpClient(opener=opener),
        page_access_token="test-token",
    )
    social.register_provider("meta", meta)

    result = social.execute(
        "social.meta.list_pages", {}, permissions={Permission.READ_SOCIAL}
    )
    assert result["total"] == 1


def test_social_connector_reports_unavailable_for_unregistered_provider() -> None:
    social = SocialConnector()
    available, reason = social.capability_available("social.meta.list_pages")
    assert not available
    assert "not registered" in reason


def test_social_connector_dispatch_fails_for_unregistered_provider() -> None:
    social = SocialConnector()
    with pytest.raises(CapabilityUnavailableError, match="not registered"):
        social.execute("social.meta.list_pages", {}, permissions=set())


def test_social_connector_permissions_declared() -> None:
    social = SocialConnector()
    perms = social.CAPABILITY_PERMISSIONS
    assert perms["social.meta.publish_post"] is Permission.PUBLISH_SOCIAL
    assert perms["social.meta.get_post"] is Permission.READ_SOCIAL
    assert perms["social.linkedin.publish_post"] is Permission.PUBLISH_SOCIAL


def test_social_connector_capability_list() -> None:
    social = SocialConnector()
    caps = social.get_capabilities()
    assert "social.meta.publish_post" in caps
    assert "social.meta.get_post" in caps
    assert "social.linkedin.get_post" in caps
    assert "social.x.get_post" in caps
    assert "social.reddit.get_post" in caps
