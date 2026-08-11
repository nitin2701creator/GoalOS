"""API end-to-end tests for the autonomous agent workflow.

Creates a real Organigram business goal, runs the workflow through the
existing orchestrator (WorkflowService + agent factory + agent runtime),
and verifies every artifact is persisted and queryable.
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

ORGANIGRAM_REQUIREMENT = (
    "Research SEO keywords and analyze the Organigram website's SEO at "
    "https://www.organigram.com to improve organic search performance."
)


@pytest.fixture
def api(tmp_path: Path):
    """TestClient whose database dependency points at an isolated file DB."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'agent_workflow_e2e.db'}",
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
    """Create the Organigram goal -> project -> workflow chain."""
    goal_response = client.post(
        "/api/v1/goals",
        json={
            "title": "Improve Organigram organic search performance",
            "description": (
                "Research SEO keywords and analyze the Organigram website's SEO "
                "to grow organic traffic."
            ),
            "executive_owner": "CMO",
            "department": "Marketing",
            "priority": "High",
        },
    )
    assert goal_response.status_code == 201
    goal_id = goal_response.json()["id"]

    project_response = client.post(
        "/api/v1/projects",
        json={
            "goal_id": goal_id,
            "title": "Organigram SEO research",
            "description": "Keyword research and website analysis for Organigram.",
            "owner": "Growth",
            "department": "Marketing",
            "priority": "High",
        },
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    workflow_response = client.post(
        "/api/v1/workflows",
        json={"project_id": project_id, "name": "Organigram SEO workflow"},
    )
    assert workflow_response.status_code == 201
    return workflow_response.json()["id"]


def test_full_organigram_workflow_via_api(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """The Organigram goal runs end to end and everything is persisted.

    The web search provider is configured and the HTTP transport is faked,
    so the REAL fetch/crawl/search pipelines run hermetically.
    """
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", make_fake_opener())
    client = api
    workflow_id = _create_goal_project_workflow(client)

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/run-agent",
        json={"requirement": ORGANIGRAM_REQUIREMENT},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Completed"
    assert body["progress_percentage"] == 100
    assert body["requirement"] == ORGANIGRAM_REQUIREMENT
    assert body["evaluation"]["passed"] is True
    assert body["evaluation"]["completed_steps"] == 4

    capabilities = [step["capability"] for step in body["steps"]]
    assert capabilities == ["keyword_research", "website_analysis", "content_analysis", "web_research"]
    assert all(step["status"] == "Completed" for step in body["steps"])

    # keyword_research and web_research came from the REAL search pipeline.
    keyword_results = body["results"]["keyword_research"]
    assert keyword_results.get("source") == "web.search"
    assert "Organigram SEO Guide" in keyword_results["keywords"]
    web_findings = body["results"]["web_research"]["findings"]
    assert web_findings[0]["title"] == "Organigram SEO Guide"

    # website_analysis came from the REAL crawl pipeline with SEO findings.
    website_results = body["results"]["website_analysis"]
    assert website_results.get("source") == "website.crawl"
    assert website_results["total_pages"] >= 2
    page_findings = " ".join(website_results["findings"])
    assert "missing canonical" not in page_findings
    assert "multiple H1s" in page_findings  # the /about fixture has two H1s

    # The workflow GET endpoint shows the persisted run.
    persisted = client.get(f"/api/v1/workflows/{workflow_id}")
    assert persisted.status_code == 200
    assert persisted.json()["status"] == "Completed"
    assert persisted.json()["evaluation"]["passed"] is True

    # The agent and skills created by GoalOS are queryable.
    agents = client.get("/api/v1/agents")
    assert agents.status_code == 200
    assert [agent["name"] for agent in agents.json()] == ["Keyword Research Agent"]

    # Resolving the same requirement now finds the existing agent.
    resolved = client.post(
        "/api/v1/agents/resolve",
        json={"requirement": ORGANIGRAM_REQUIREMENT},
    )
    assert resolved.status_code == 200
    assert resolved.json()["agent"]["name"] == "Keyword Research Agent"


def test_duplicate_workflow_run_rejected_via_api(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """Running the same workflow twice returns a 400."""
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", make_fake_opener())
    client = api
    workflow_id = _create_goal_project_workflow(client)

    first = client.post(
        f"/api/v1/workflows/{workflow_id}/run-agent",
        json={"requirement": ORGANIGRAM_REQUIREMENT},
    )
    assert first.status_code == 200
    assert first.json()["status"] == "Completed"

    second = client.post(
        f"/api/v1/workflows/{workflow_id}/run-agent",
        json={"requirement": ORGANIGRAM_REQUIREMENT},
    )
    assert second.status_code == 400
    assert "already been run" in second.json()["detail"]


def test_workflow_fails_honestly_when_integration_unconfigured(api) -> None:
    """A required integration that is not configured blocks the workflow.

    No search provider is configured here, so the ``web.search`` capability
    is unavailable; the workflow must fail with the reason persisted — not
    fabricate results.
    """
    client = api
    workflow_id = _create_goal_project_workflow(client)

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/run-agent",
        json={"requirement": ORGANIGRAM_REQUIREMENT},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Failed"
    assert "web.search" in (body["error_message"] or "")
    assert body["evaluation"]["passed"] is False
    assert body["steps"]
    for step in body["steps"]:
        if step["capability"] in ("keyword_research", "web_research"):
            assert step["status"] == "Blocked"
            assert "web.search" in step["error"]
        else:
            assert step["status"] == "Pending"

    # The persisted workflow keeps the blocked reason after a restart.
    persisted = client.get(f"/api/v1/workflows/{workflow_id}")
    assert persisted.json()["status"] == "Failed"
    assert "web.search" in (persisted.json()["error_message"] or "")


def test_unresolvable_workflow_run_fails_via_api(api) -> None:
    """A requirement GoalOS cannot resolve fails with a persisted reason."""
    client = api
    workflow_id = _create_goal_project_workflow(client)

    response = client.post(
        f"/api/v1/workflows/{workflow_id}/run-agent",
        json={"requirement": "xyzzy zork"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "Failed"
    assert body["error_message"] == "no capabilities could be resolved from the requirement"
    assert body["evaluation"]["passed"] is False
    assert body["steps"] == []


def test_run_agent_workflow_missing_workflow_via_api(api) -> None:
    """Running a nonexistent workflow returns a 404."""
    client = api
    response = client.post(
        "/api/v1/workflows/00000000-0000-0000-0000-000000000000/run-agent",
        json={"requirement": ORGANIGRAM_REQUIREMENT},
    )
    assert response.status_code == 404
