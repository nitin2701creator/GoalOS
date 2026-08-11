"""API tests for the GoalOS capability engine.

Covers the real API path: capability listing/registration/resolution/
matching, execution through the existing runtime, the workflow path using
the capability engine (agent reuse/create), and the OpenWebUI-compatible
chat path invoking capability resolution. External services run through
the shared fake transport; nothing is fabricated.
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
from tests.integration_helpers import make_fake_opener

API_KEY = "goalos-capability-key"
AUTH = {"Authorization": f"Bearer {API_KEY}"}

SEO_GOAL = (
    "Analyse Organigram's website SEO at https://www.organigram.com."
)
CALCULATION_GOAL = "Create an agent capable of calculating the sum of two numbers."


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with an isolated DB and the OpenWebUI API key configured."""
    monkeypatch.setenv("GOALOS_OPENWEBUI_API_KEY", API_KEY)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'capabilities_api.db'}",
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


def _create_goal_project_workflow(client: TestClient) -> str:
    goal = client.post(
        "/api/v1/goals",
        json={
            "title": "Capability engine acceptance",
            "description": "Run a goal through the capability engine.",
            "executive_owner": "CMO",
            "department": "Marketing",
            "priority": "High",
        },
    )
    assert goal.status_code == 201
    project = client.post(
        "/api/v1/projects",
        json={
            "goal_id": goal.json()["id"],
            "title": "Capability acceptance project",
            "description": "Goal through the capability engine.",
            "owner": "Growth",
            "department": "Marketing",
            "priority": "High",
        },
    )
    assert project.status_code == 201
    workflow = client.post(
        "/api/v1/workflows",
        json={"project_id": project.json()["id"], "name": "Capability acceptance"},
    )
    assert workflow.status_code == 201
    return workflow.json()["id"]


def test_list_capabilities_with_availability(api) -> None:
    """GET /api/v1/capabilities lists the registry with honest status."""
    response = api.get("/api/v1/capabilities")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 20
    names = {item["name"] for item in body["capabilities"]}
    assert {"seo_audit", "web_search", "website_crawl", "whatsapp_send"} <= names
    by_name = {item["name"]: item for item in body["capabilities"]}
    # Honest availability: website crawl works without config, WhatsApp does not.
    assert by_name["website_crawl"]["available"] is True
    assert by_name["whatsapp_send"]["available"] is False
    assert "INTEGRATION_NOT_CONFIGURED" in by_name["whatsapp_send"]["availability_reason"]


def test_register_capability_idempotent(api) -> None:
    """POST /api/v1/capabilities registers; duplicates return the same id."""
    payload = {
        "name": "custom_api_capability",
        "description": "Registered through the API.",
        "category": "test",
        "provider_type": "native",
        "provider": "native",
        "implementation": "calculation",
    }
    first = api.post("/api/v1/capabilities", json=payload)
    assert first.status_code == 201
    second = api.post("/api/v1/capabilities", json=payload)
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]

    retrieved = api.get("/api/v1/capabilities/custom_api_capability")
    assert retrieved.status_code == 200
    assert retrieved.json()["exists"] is True


def test_resolve_capability_endpoint(api) -> None:
    """POST /api/v1/capabilities/resolve returns the honest outcome."""
    response = api.post("/api/v1/capabilities/resolve", json={"name": "calculation"})
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["available"] is True
    assert body["execution_capability"] == "calculation"

    missing = api.post("/api/v1/capabilities/resolve", json={"name": "nope"})
    assert missing.json()["exists"] is False


def test_resolve_many_endpoint(api) -> None:
    response = api.post(
        "/api/v1/capabilities/resolve-many",
        json={"names": ["seo_audit", "gmail_send"]},
    )
    assert response.status_code == 200
    results = {item["name"]: item for item in response.json()}
    assert results["seo_audit"]["available"] is True
    assert results["gmail_send"]["available"] is False
    assert results["gmail_send"]["required_permissions"] == ["SEND_EMAIL"]


def test_match_goal_endpoint(api) -> None:
    """POST /api/v1/capabilities/match resolves a goal to capabilities."""
    response = api.post("/api/v1/capabilities/match", json={"requirement": SEO_GOAL})
    assert response.status_code == 200
    body = response.json()
    assert "seo_audit" in body["capabilities"]
    assert "website_crawl" in body["capabilities"]
    assert body["execution_capabilities"] == ["keyword_research", "website_analysis"]


def test_execute_calculation_acceptance(api) -> None:
    """The acceptance flow: resolve calculation -> execute -> 42.

    No mock: the real native skill runs through the existing runtime, and
    EXECUTE_CODE must be explicitly granted.
    """
    resolved = api.post("/api/v1/capabilities/resolve", json={"name": "calculation"})
    assert resolved.json()["execution_capability"] == "calculation"

    denied = api.post(
        "/api/v1/capabilities/calculation/execute",
        json={"params": {"a": 40, "b": 2}, "permissions": []},
    )
    assert denied.status_code == 200
    assert denied.json()["status"] == "PERMISSION_DENIED"

    result = api.post(
        "/api/v1/capabilities/calculation/execute",
        json={"params": {"a": 40, "b": 2}, "permissions": ["EXECUTE_CODE"]},
    )
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "OK"
    assert body["result"] == {"result": 42.0}


def test_execute_unconfigured_reports_honestly(api) -> None:
    """Unconfigured integrations report INTEGRATION_NOT_CONFIGURED, never fake data."""
    response = api.post(
        "/api/v1/capabilities/web_search/execute",
        json={"params": {"query": "organigram"}, "permissions": ["READ_WEBSITE"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INTEGRATION_NOT_CONFIGURED"
    assert "search provider" in (body["error"] or "")


def test_workflow_uses_capability_engine_and_reuses_agent(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A goal run resolves capabilities, reuses/creates the agent, executes.

    The real crawl + search pipelines run hermetically through the fake
    transport; the workflow persists the resolved capability names.
    """
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", make_fake_opener())

    first_id = _create_goal_project_workflow(api)
    first = api.post(
        f"/api/v1/workflows/{first_id}/run-agent",
        json={"requirement": SEO_GOAL},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "Completed"
    assert body["evaluation"]["passed"] is True
    assert set(body["resolved_capabilities"]) >= {
        "seo_audit",
        "website_crawl",
        "keyword_research",
    }
    assert [step["capability"] for step in body["steps"]] == [
        "keyword_research",
        "website_analysis",
    ]
    assert all(step["status"] == "Completed" for step in body["steps"])
    # The execution came from the real search + crawl pipelines.
    assert body["results"]["keyword_research"]["source"] == "web.search"
    assert body["results"]["website_analysis"]["source"] == "website.crawl"

    # The capability engine created exactly one agent ("Keyword Research Agent").
    agents = api.get("/api/v1/agents").json()
    assert [agent["name"] for agent in agents] == ["Keyword Research Agent"]

    # A second goal whose capabilities are a SUBSET REUSES the existing agent.
    second_id = _create_goal_project_workflow(api)
    second = api.post(
        f"/api/v1/workflows/{second_id}/run-agent",
        json={"requirement": "Generate keyword terms for the topic."},
    )
    assert second.status_code == 200
    assert second.json()["status"] == "Completed"
    assert [step["capability"] for step in second.json()["steps"]] == [
        "keyword_research"
    ]
    assert len(api.get("/api/v1/agents").json()) == 1


def test_workflow_creates_agent_when_none_capable(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fresh requirement creates a capable agent through the factory."""
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", make_fake_opener())
    workflow_id = _create_goal_project_workflow(api)
    response = api.post(
        f"/api/v1/workflows/{workflow_id}/run-agent",
        json={"requirement": "Find potential distributors for Organigram."},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Completed"
    assert body["resolved_capabilities"]
    # company_discovery ran the REAL search pipeline and the agent was named
    # from its first execution capability (website_analysis).
    assert body["results"]["company_discovery"]["source"] == "web.search"
    agents = api.get("/api/v1/agents").json()
    assert len(agents) == 1
    assert agents[0]["name"] == "Website Analysis Agent"
    assert "company_discovery" in agents[0]["capabilities"]


def test_chat_path_invokes_capability_engine(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """The OpenWebUI-compatible chat endpoint resolves capabilities via the engine."""
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", make_fake_opener())

    response = api.post(
        "/v1/chat/completions",
        headers=AUTH,
        json={
            "model": "goalos-autonomous",
            "messages": [{"role": "user", "content": SEO_GOAL}],
        },
    )
    assert response.status_code == 200
    content = response.json()["choices"][0]["message"]["content"]
    assert "Completed" in content

    workflows = api.get("/api/v1/workflows").json()
    run = workflows[0]
    assert run["status"] == "Completed"
    assert set(run["resolved_capabilities"]) >= {"seo_audit", "website_crawl"}
    # The execution came from the real crawl + search pipelines.
    assert run["results"]["keyword_research"]["source"] == "web.search"
    assert run["results"]["website_analysis"]["source"] == "website.crawl"
