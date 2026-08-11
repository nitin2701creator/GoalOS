"""API tests for the GoalOS execution runtime.

Proves the real API path: POST /api/v1/executions/runtime executes a
capability through the runtime and persists the full lifecycle, permission
gates and unavailable integrations are reported honestly (never
fabricated), and an approved workflow runs through POST
/api/v1/workflows/{id}/run-runtime with one persisted runtime execution
per step. External services run through the shared fake transport.
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
from tests.integration_helpers import FakeUrlOpener

SEO_GOAL = (
    "Analyse Organigram's website SEO at https://www.organigram.com."
)


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with an isolated DB and a hermetic HTTP transport."""
    monkeypatch.setenv("GOALOS_OPENWEBUI_API_KEY", "runtime-test-key")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'runtime_api.db'}",
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


def _create_workflow(client: TestClient) -> str:
    goal = client.post(
        "/api/v1/goals",
        json={
            "title": "Execution runtime acceptance",
            "description": "Run a goal through the execution runtime.",
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
            "title": "Runtime acceptance project",
            "description": "Goal through the execution runtime.",
            "owner": "Growth",
            "department": "Marketing",
            "priority": "High",
        },
    )
    assert project.status_code == 201
    workflow = client.post(
        "/api/v1/workflows",
        json={"project_id": project.json()["id"], "name": "Runtime acceptance"},
    )
    assert workflow.status_code == 201
    return workflow.json()["id"]


def test_execute_capability_through_runtime_api(api) -> None:
    """POST /api/v1/executions/runtime executes and persists the lifecycle."""
    response = api.post(
        "/api/v1/executions/runtime",
        json={
            "capability": "calculation",
            "params": {"a": 40, "b": 2},
            "permissions": ["EXECUTE_CODE"],
            "agent_name": "api-caller",
            "metadata": {"source": "api-test"},
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "succeeded"
    assert body["output"] == {"result": 42.0}
    assert body["error"] is None
    assert body["agent_name"] == "api-caller"
    assert body["input"] == {"a": 40, "b": 2}
    assert body["permissions_required"] == ["EXECUTE_CODE"]
    assert body["execution_metadata"]["source"] == "api-test"
    assert body["started_at"] is not None
    assert body["completed_at"] is not None

    # Fetch it back by id.
    fetched = api.get(f"/api/v1/executions/runtime/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["status"] == "succeeded"

    # Listed.
    listed = api.get("/api/v1/executions/runtime")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]


def test_runtime_api_denies_without_permission(api) -> None:
    """Missing permission is persisted as failed, never silently granted."""
    response = api.post(
        "/api/v1/executions/runtime",
        json={"capability": "calculation", "params": {"a": 1, "b": 2}},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert "missing required permissions" in (body["error"] or "")
    assert "EXECUTE_CODE" in body["error"]


def test_runtime_api_reports_integration_not_configured(api) -> None:
    """An unconfigured provider fails honestly with INTEGRATION_NOT_CONFIGURED."""
    response = api.post(
        "/api/v1/executions/runtime",
        json={
            "capability": "web_search",
            "params": {"query": "organigram seo"},
            "permissions": ["READ_WEBSITE"],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert "INTEGRATION_NOT_CONFIGURED" in (body["error"] or "")
    assert body["output"] is None


def test_runtime_api_unregistered_capability(api) -> None:
    response = api.post(
        "/api/v1/executions/runtime",
        json={"capability": "no_such_capability", "params": {}},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "failed"
    assert body["error"] == "capability is not registered"


def test_runtime_api_missing_execution_404(api) -> None:
    import uuid

    response = api.get(f"/api/v1/executions/runtime/{uuid.uuid4()}")
    assert response.status_code == 404


def test_workflow_approve_then_run_runtime(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Approve a workflow, then run it through the runtime end to end.

    With the search provider configured and the transport faked, the REAL
    web.search and website.crawl pipelines execute hermetically and one
    runtime execution is persisted per step.
    """
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    workflow_id = _create_workflow(api)

    approved = api.post(
        f"/api/v1/workflows/{workflow_id}/approve",
        json={"requirement": SEO_GOAL},
    )
    assert approved.status_code == 200
    assert approved.json()["requirement"] == SEO_GOAL
    assert len(approved.json()["resolved_capabilities"]) >= 2

    run = api.post(
        f"/api/v1/workflows/{workflow_id}/run-runtime",
        json={"agent_name": "api-workflow-runner"},
    )
    assert run.status_code == 200
    body = run.json()
    assert body["workflow"]["status"] == "Completed"
    assert body["workflow"]["evaluation"]["passed"] is True
    steps = {step["capability"]: step for step in body["workflow"]["steps"]}
    assert set(steps) == {"keyword_research", "website_analysis"}
    assert all(step["status"] == "Completed" for step in steps.values())
    assert body["workflow"]["results"]["keyword_research"]["source"] == "web.search"
    assert body["workflow"]["results"]["website_analysis"]["source"] == "website.crawl"

    # One persisted runtime execution per step, workflow-scoped.
    assert len(body["executions"]) == 2
    assert {item["capability"] for item in body["executions"]} == {
        "keyword_research",
        "website_analysis",
    }
    assert all(item["status"] == "succeeded" for item in body["executions"])
    assert all(item["workflow_id"] == workflow_id for item in body["executions"])

    # Workflow-scoped listing via the query param.
    listed = api.get(f"/api/v1/executions/runtime?workflow_id={workflow_id}")
    assert listed.status_code == 200
    assert len(listed.json()) == 2

    # Duplicate run is refused.
    duplicate = api.post(
        f"/api/v1/workflows/{workflow_id}/run-runtime",
        json={"agent_name": "api-workflow-runner"},
    )
    assert duplicate.status_code == 400
    assert "already been run" in duplicate.json()["detail"]


def test_workflow_run_runtime_reports_blocked_integration(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a search provider the run fails honestly; nothing is faked."""
    monkeypatch.delenv("GOALOS_SEARCH_PROVIDER", raising=False)

    workflow_id = _create_workflow(api)
    approved = api.post(
        f"/api/v1/workflows/{workflow_id}/approve",
        json={"requirement": SEO_GOAL},
    )
    assert approved.status_code == 200

    run = api.post(
        f"/api/v1/workflows/{workflow_id}/run-runtime",
        json={"agent_name": "api-workflow-runner"},
    )
    assert run.status_code == 200
    body = run.json()
    assert body["workflow"]["status"] == "Failed"
    assert body["workflow"]["evaluation"]["passed"] is False
    assert "web.search" in (body["workflow"]["error_message"] or "")
    blocked = {
        step["capability"]: step for step in body["workflow"]["steps"]
    }
    assert blocked["keyword_research"]["status"] == "Blocked"
    # The blocked step has a persisted BLOCKED execution carrying the reason.
    blocked_executions = [
        item for item in body["executions"] if item["status"] == "blocked"
    ]
    assert len(blocked_executions) == 1
    assert blocked_executions[0]["capability"] == "keyword_research"
    assert blocked_executions[0]["error_code"] == "INTEGRATION_NOT_CONFIGURED"
    assert "web.search" in (blocked_executions[0]["error"] or "")


def test_existing_execution_endpoints_still_work(api) -> None:
    """Backward compatibility: the task-bound execution surface is intact."""
    # Existing list endpoint works (empty in a fresh DB).
    response = api.get("/api/v1/executions")
    assert response.status_code == 200
    assert response.json() == []

    # Task execution create still works with the classic shape.
    goal = api.post(
        "/api/v1/goals",
        json={
            "title": "Runtime compat goal",
            "description": "Backward compat.",
            "executive_owner": "CMO",
            "department": "Marketing",
            "priority": "High",
        },
    )
    assert goal.status_code == 201
    project = api.post(
        "/api/v1/projects",
        json={
            "goal_id": goal.json()["id"],
            "title": "Runtime compat project",
            "description": "Backward compat.",
            "owner": "Growth",
            "department": "Marketing",
            "priority": "High",
        },
    )
    assert project.status_code == 201
    task = api.post(
        "/api/v1/tasks",
        json={
            "project_id": project.json()["id"],
            "title": "Runtime compat task",
            "description": "Backward compat.",
            "priority": "High",
        },
    )
    assert task.status_code == 201
    execution = api.post(
        "/api/v1/executions",
        json={
            "task_id": task.json()["id"],
            "agent_name": "compat-worker",
        },
    )
    assert execution.status_code == 201
    assert execution.json()["status"] == "Pending"
    assert execution.json()["task_id"] == task.json()["id"]

    # Runtime list is separate from task-bound executions.
    runtime = api.get("/api/v1/executions/runtime")
    assert runtime.status_code == 200
    assert runtime.json() == []
