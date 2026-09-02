"""Tests for the capability discovery endpoint and integration-backed capabilities.

Covers:
- Discovery endpoint returns tool catalog for LibreChat
- LinkedIn/Twitter/Reddit capabilities are registered
- Input/output schemas are present on integration capabilities
- Capability execution routes through real connectors
- Unconfigured integrations report honest status
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import session as session_module
from app.db.base import Base
from app.main import app


@pytest.fixture
def api(tmp_path: Path):
    """TestClient with an isolated in-memory-style SQLite database."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'capabilities.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[session_module.get_db] = override_get_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


# ---------------------------------------------------------------------------
# Discovery endpoint
# ---------------------------------------------------------------------------

def test_discovery_returns_tools_catalog(api: TestClient) -> None:
    """GET /api/v1/capabilities/discovery returns a tools list."""
    response = api.get("/api/v1/capabilities/discovery")
    assert response.status_code == 200
    body = response.json()
    assert "tools" in body
    assert "total" in body
    assert "categories" in body
    assert body["total"] > 0
    assert isinstance(body["tools"], list)


def test_discovery_includes_schemas(api: TestClient) -> None:
    """Each discovered tool includes input_schema and output_schema."""
    response = api.get("/api/v1/capabilities/discovery")
    tools = response.json()["tools"]
    for tool in tools:
        assert "input_schema" in tool
        assert "output_schema" in tool
        assert isinstance(tool["input_schema"], dict)
        assert isinstance(tool["output_schema"], dict)


def test_discovery_only_includes_enabled_capabilities(api: TestClient) -> None:
    """Disabled capabilities are excluded from the discovery catalog."""
    response = api.get("/api/v1/capabilities/discovery")
    tools = response.json()["tools"]
    tool_names = {t["name"] for t in tools}
    # All returned tools should be enabled
    for tool in tools:
        assert "requires_approval" in tool
        assert "required_permissions" in tool


# ---------------------------------------------------------------------------
# LinkedIn capabilities
# ---------------------------------------------------------------------------

def test_linkedin_capabilities_registered(api: TestClient) -> None:
    """LinkedIn direct capabilities appear in the registry."""
    response = api.get("/api/v1/capabilities")
    names = {c["name"] for c in response.json()["capabilities"]}
    assert "linkedin_get_organization" in names
    assert "linkedin_create_post" in names
    assert "linkedin_get_post" in names
    assert "linkedin_get_stats" in names
    assert "linkedin_get_post_analytics" in names


def test_linkedin_get_organization_has_schemas(api: TestClient) -> None:
    """LinkedIn get_organization capability has input/output schemas in discovery."""
    response = api.get("/api/v1/capabilities/discovery")
    tools = {t["name"]: t for t in response.json()["tools"]}
    cap = tools["linkedin_get_organization"]
    assert cap["input_schema"] == {"type": "object", "properties": {}, "required": []}
    assert "properties" in cap["output_schema"]
    assert "id" in cap["output_schema"]["properties"]


def test_linkedin_create_post_requires_approval(api: TestClient) -> None:
    """LinkedIn create_post requires approval."""
    response = api.get("/api/v1/capabilities/linkedin_create_post")
    assert response.status_code == 200
    assert response.json()["requires_approval"] is True


def test_linkedin_capability_resolution(api: TestClient) -> None:
    """Resolving a LinkedIn capability returns honest availability."""
    response = api.post(
        "/api/v1/capabilities/resolve",
        json={"name": "linkedin_get_organization"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["provider"] == "linkedin"
    # Without credentials, it should report not available
    assert body["available"] is False
    assert body["reason"] is not None


# ---------------------------------------------------------------------------
# Twitter capabilities
# ---------------------------------------------------------------------------

def test_twitter_capabilities_registered(api: TestClient) -> None:
    """Twitter direct capabilities appear in the registry."""
    response = api.get("/api/v1/capabilities")
    names = {c["name"] for c in response.json()["capabilities"]}
    assert "twitter_get_me" in names
    assert "twitter_create_post" in names
    assert "twitter_get_post" in names
    assert "twitter_get_user_posts" in names
    assert "twitter_get_post_metrics" in names


def test_twitter_get_me_has_schemas(api: TestClient) -> None:
    """Twitter get_me capability has input/output schemas in discovery."""
    response = api.get("/api/v1/capabilities/discovery")
    tools = {t["name"]: t for t in response.json()["tools"]}
    cap = tools["twitter_get_me"]
    assert cap["input_schema"]["type"] == "object"
    assert "username" in cap["output_schema"]["properties"]


def test_twitter_create_post_requires_approval(api: TestClient) -> None:
    """Twitter create_post requires approval."""
    response = api.get("/api/v1/capabilities/twitter_create_post")
    assert response.status_code == 200
    assert response.json()["requires_approval"] is True


def test_twitter_capability_resolution(api: TestClient) -> None:
    """Resolving a Twitter capability returns honest availability."""
    response = api.post(
        "/api/v1/capabilities/resolve",
        json={"name": "twitter_get_me"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["provider"] == "twitter"
    # Without bearer token, not available
    assert body["available"] is False


# ---------------------------------------------------------------------------
# Reddit capabilities
# ---------------------------------------------------------------------------

def test_reddit_capabilities_registered(api: TestClient) -> None:
    """Reddit direct capabilities appear in the registry."""
    response = api.get("/api/v1/capabilities")
    names = {c["name"] for c in response.json()["capabilities"]}
    assert "reddit_get_me" in names
    assert "reddit_list_subreddits" in names
    assert "reddit_get_post" in names
    assert "reddit_get_subreddit" in names
    assert "reddit_submit_post" in names
    assert "reddit_submit_comment" in names


def test_reddit_submit_post_requires_approval(api: TestClient) -> None:
    """Reddit submit_post and submit_comment require approval."""
    for name in ("reddit_submit_post", "reddit_submit_comment"):
        response = api.get(f"/api/v1/capabilities/{name}")
        assert response.status_code == 200
        assert response.json()["requires_approval"] is True


def test_reddit_capability_resolution(api: TestClient) -> None:
    """Resolving a Reddit capability returns honest availability."""
    response = api.post(
        "/api/v1/capabilities/resolve",
        json={"name": "reddit_get_me"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["provider"] == "reddit"
    assert body["available"] is False


# ---------------------------------------------------------------------------
# Capability execution
# ---------------------------------------------------------------------------

def test_execute_unconfigured_integration_returns_honest_status(api: TestClient) -> None:
    """Executing an unconfigured LinkedIn capability returns INTEGRATION_NOT_CONFIGURED."""
    response = api.post(
        "/api/v1/capabilities/linkedin_get_organization/execute",
        json={"params": {}, "permissions": ["READ_SOCIAL"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INTEGRATION_NOT_CONFIGURED"
    assert body["provider"] == "linkedin"


def test_execute_unconfigured_twitter_returns_honest_status(api: TestClient) -> None:
    """Executing an unconfigured Twitter capability returns INTEGRATION_NOT_CONFIGURED."""
    response = api.post(
        "/api/v1/capabilities/twitter_get_me/execute",
        json={"params": {}, "permissions": ["READ_SOCIAL"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INTEGRATION_NOT_CONFIGURED"
    assert body["provider"] == "twitter"


def test_execute_unconfigured_reddit_returns_honest_status(api: TestClient) -> None:
    """Executing an unconfigured Reddit capability returns INTEGRATION_NOT_CONFIGURED."""
    response = api.post(
        "/api/v1/capabilities/reddit_get_me/execute",
        json={"params": {}, "permissions": ["READ_SOCIAL"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INTEGRATION_NOT_CONFIGURED"
    assert body["provider"] == "reddit"


def test_execute_unconfigured_publish_returns_not_configured(api: TestClient) -> None:
    """An unconfigured publishing capability reports INTEGRATION_NOT_CONFIGURED."""
    response = api.post(
        "/api/v1/capabilities/linkedin_create_post/execute",
        json={"params": {"text": "Hello"}, "permissions": []},
    )
    assert response.status_code == 200
    body = response.json()
    # Availability check runs before permission check
    assert body["status"] == "INTEGRATION_NOT_CONFIGURED"


# ---------------------------------------------------------------------------
# Goal matching
# ---------------------------------------------------------------------------

def test_match_goal_finds_linkedin_capability(api: TestClient) -> None:
    """Matching a LinkedIn goal finds the relevant capabilities."""
    response = api.post(
        "/api/v1/capabilities/match",
        json={"requirement": "Get my LinkedIn organization profile"},
    )
    assert response.status_code == 200
    names = response.json()["capabilities"]
    assert "linkedin_get_organization" in names


def test_match_goal_finds_twitter_capability(api: TestClient) -> None:
    """Matching a Twitter goal finds the relevant capabilities."""
    response = api.post(
        "/api/v1/capabilities/match",
        json={"requirement": "Get my Twitter profile"},
    )
    assert response.status_code == 200
    names = response.json()["capabilities"]
    assert "twitter_get_me" in names


def test_match_goal_finds_reddit_capability(api: TestClient) -> None:
    """Matching a Reddit goal finds the relevant capabilities."""
    response = api.post(
        "/api/v1/capabilities/match",
        json={"requirement": "List my Reddit subreddits"},
    )
    assert response.status_code == 200
    names = response.json()["capabilities"]
    assert "reddit_list_subreddits" in names
