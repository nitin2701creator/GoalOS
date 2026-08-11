"""API tests for the GoalOS persisted scheduler, workflow control, and
deployment readiness.

Proves the real API path end to end: permission-gated schedule creation,
schedule enable/disable/cancel, due-run execution through the execution
runtime (hermetic fake transport), manual run-now, workflow pause/resume/
cancel (in-flight executions persisted as cancelled), workflow retry,
execution history filters, execution retry, and the /health + /ready
endpoints.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.db import session as session_module
from app.db.base import Base
from app.main import app
from tests.integration_helpers import FakeUrlOpener

SEO_GOAL = "Analyse Organigram's website SEO at https://www.organigram.com."


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with an isolated DB and a hermetic HTTP transport."""
    monkeypatch.setenv("GOALOS_OPENWEBUI_API_KEY", "schedules-test-key")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'schedules_api.db'}",
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
            yield client, engine
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _create_workflow(client: TestClient) -> str:
    goal = client.post(
        "/api/v1/goals",
        json={
            "title": "Scheduler acceptance",
            "description": "Schedule a goal through the API.",
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
            "title": "Scheduler project",
            "description": "Goal through the scheduler API.",
            "owner": "Growth",
            "department": "Marketing",
            "priority": "High",
        },
    )
    assert project.status_code == 201
    workflow = client.post(
        "/api/v1/workflows",
        json={"project_id": project.json()["id"], "name": "Scheduled workflow"},
    )
    assert workflow.status_code == 201
    approved = client.post(
        f"/api/v1/workflows/{workflow.json()['id']}/approve",
        json={"requirement": SEO_GOAL},
    )
    assert approved.status_code == 200
    return workflow.json()["id"]


def _make_due(engine, workflow_id: str) -> None:
    """Backdate a schedule so it is due (SQLite stores UUIDs dashless)."""
    with engine.connect() as connection:
        connection.execute(
            text(
                "UPDATE workflows SET next_run_at = '2000-01-01 00:00:00.000000' "
                "WHERE id = :id"
            ),
            {"id": workflow_id.replace("-", "")},
        )
        connection.commit()


# ----------------------------------------------------------------------
# Schedules
# ----------------------------------------------------------------------
def test_schedule_creation_requires_schedule_workflows_permission(api) -> None:
    client, _ = api
    workflow_id = _create_workflow(client)

    denied = client.post(
        "/api/v1/schedules",
        json={"workflow_id": workflow_id, "schedule": "daily", "requirement": SEO_GOAL},
    )
    assert denied.status_code == 400
    assert "PERMISSION_DENIED" in denied.json()["detail"]
    assert "SCHEDULE_WORKFLOWS" in denied.json()["detail"]

    created = client.post(
        "/api/v1/schedules",
        json={
            "workflow_id": workflow_id,
            "schedule": "daily",
            "requirement": SEO_GOAL,
            "permissions": ["SCHEDULE_WORKFLOWS"],
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["schedule"] == "daily"
    assert body["enabled"] is True
    assert body["next_run_at"] is not None


def test_schedule_list_disable_enable_cancel(api) -> None:
    client, _ = api
    workflow_id = _create_workflow(client)
    client.post(
        "/api/v1/schedules",
        json={
            "workflow_id": workflow_id,
            "schedule": "weekly",
            "requirement": SEO_GOAL,
            "permissions": ["SCHEDULE_WORKFLOWS"],
        },
    )

    listed = client.get("/api/v1/schedules")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["workflow_id"] == workflow_id
    assert rows[0]["schedule"] == "weekly"

    disabled = client.post(f"/api/v1/schedules/{workflow_id}/disable")
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled.json()["schedule"] == "weekly"

    enabled = client.post(f"/api/v1/schedules/{workflow_id}/enable")
    assert enabled.status_code == 200
    assert enabled.json()["enabled"] is True

    cancelled = client.delete(f"/api/v1/schedules/{workflow_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["enabled"] is False
    assert cancelled.json()["schedule"] is None


# ----------------------------------------------------------------------
# Due-run + manual trigger
# ----------------------------------------------------------------------
def test_run_due_executes_scheduled_workflow(
    api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """run-due executes a due schedule through the runtime end to end."""
    client, engine = api
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    workflow_id = _create_workflow(client)
    client.post(
        "/api/v1/schedules",
        json={
            "workflow_id": workflow_id,
            "schedule": "daily",
            "requirement": SEO_GOAL,
            "permissions": ["SCHEDULE_WORKFLOWS"],
        },
    )
    _make_due(engine, workflow_id)

    tick = client.post("/api/v1/schedules/run-due")
    assert tick.status_code == 200
    body = tick.json()
    assert body["due"] == 1
    processed = body["processed"][0]
    assert processed["status"] == "Completed"
    assert processed["run_workflow_id"]
    assert processed["executions"] == 2

    run_id = processed["run_workflow_id"]
    run = client.get(f"/api/v1/workflows/{run_id}")
    assert run.status_code == 200
    assert run.json()["status"] == "Completed"
    assert run.json()["scheduled_from_id"] == workflow_id

    # One persisted runtime execution per step, workflow-scoped.
    executions = client.get(f"/api/v1/executions/runtime?workflow_id={run_id}")
    assert executions.status_code == 200
    assert len(executions.json()) == 2
    assert {item["status"] for item in executions.json()} == {"succeeded"}

    # Template advanced: a second tick runs nothing.
    second = client.post("/api/v1/schedules/run-due")
    assert second.json()["due"] == 0


def test_run_now_manually_triggers(api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = api
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    workflow_id = _create_workflow(client)
    client.post(
        "/api/v1/schedules",
        json={
            "workflow_id": workflow_id,
            "schedule": "daily",
            "requirement": SEO_GOAL,
            "permissions": ["SCHEDULE_WORKFLOWS"],
        },
    )

    run = client.post(f"/api/v1/schedules/{workflow_id}/run-now")
    assert run.status_code == 200
    body = run.json()
    assert body["workflow"]["status"] == "Completed"
    assert body["workflow"]["scheduled_from_id"] == workflow_id
    assert len(body["executions"]) == 2


def test_run_due_reports_blocked_integration_honestly(api) -> None:
    """Without a search provider the scheduled run fails honestly."""
    client, engine = api
    workflow_id = _create_workflow(client)
    client.post(
        "/api/v1/schedules",
        json={
            "workflow_id": workflow_id,
            "schedule": "daily",
            "requirement": SEO_GOAL,
            "permissions": ["SCHEDULE_WORKFLOWS"],
        },
    )
    _make_due(engine, workflow_id)

    tick = client.post("/api/v1/schedules/run-due")
    body = tick.json()
    processed = body["processed"][0]
    assert processed["status"] == "Failed"
    assert processed["evaluation"]["passed"] is False

    run = client.get(f"/api/v1/workflows/{processed['run_workflow_id']}")
    assert run.json()["status"] == "Failed"
    assert "web.search" in (run.json()["error_message"] or "")

    executions = client.get(
        f"/api/v1/executions/runtime?workflow_id={processed['run_workflow_id']}"
    )
    blocked = [item for item in executions.json() if item["status"] == "blocked"]
    assert len(blocked) == 1
    assert blocked[0]["error_code"] == "INTEGRATION_NOT_CONFIGURED"


# ----------------------------------------------------------------------
# Workflow control
# ----------------------------------------------------------------------
def test_workflow_pause_resume_cancel_via_api(api) -> None:
    client, _ = api
    workflow_id = _create_workflow(client)
    client.post(
        "/api/v1/schedules",
        json={
            "workflow_id": workflow_id,
            "schedule": "daily",
            "requirement": SEO_GOAL,
            "permissions": ["SCHEDULE_WORKFLOWS"],
        },
    )

    paused = client.post(f"/api/v1/workflows/{workflow_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "Paused"
    assert paused.json()["schedule_enabled"] is False

    resumed = client.post(f"/api/v1/workflows/{workflow_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "Pending"
    assert resumed.json()["schedule_enabled"] is True

    # Cancelling also disables the schedule.
    cancelled = client.post(f"/api/v1/workflows/{workflow_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "Cancelled"
    assert cancelled.json()["schedule_enabled"] is False
    assert cancelled.json()["next_run_at"] is None

    # Completed workflows cannot be cancelled.
    completed = client.post(f"/api/v1/workflows/{workflow_id}/start")
    assert completed.status_code == 200
    completed = client.post(f"/api/v1/workflows/{workflow_id}/complete")
    assert completed.status_code == 200
    refused = client.post(f"/api/v1/workflows/{workflow_id}/cancel")
    assert refused.status_code == 400
    assert "WORKFLOW_INVALID" in refused.json()["detail"]


def test_cancel_workflow_cancels_in_flight_executions(api) -> None:
    client, engine = api
    workflow_id = _create_workflow(client)

    # Simulate an in-flight capability execution for the workflow (SQLite
    # stores UUIDs dashless).
    execution_id = "00000000000000000000000000000001"
    with engine.connect() as connection:
        connection.execute(
            text(
                "INSERT INTO runtime_executions "
                "(id, workflow_id, capability, status, input, permissions_required, "
                " execution_metadata) "
                "VALUES (:id, :wf, 'calculation', 'running', '{}', '[]', '{}')"
            ),
            {
                "id": execution_id,
                "wf": workflow_id.replace("-", ""),
            },
        )
        connection.commit()

    cancelled = client.post(f"/api/v1/workflows/{workflow_id}/cancel")
    assert cancelled.status_code == 200

    execution = client.get(f"/api/v1/executions/runtime/{execution_id}")
    assert execution.status_code == 200
    assert execution.json()["status"] == "cancelled"
    assert execution.json()["error_code"] == "CANCELLED"


def test_retry_failed_workflow_via_api(api, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _ = api
    workflow_id = _create_workflow(client)

    # First run fails honestly (no search provider).
    failed = client.post(
        f"/api/v1/workflows/{workflow_id}/run-runtime",
        json={"agent_name": "api-runner"},
    )
    assert failed.status_code == 200
    assert failed.json()["workflow"]["status"] == "Failed"

    # Configure the integration, then retry → fresh completed instance.
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())
    retried = client.post(f"/api/v1/workflows/{workflow_id}/retry")
    assert retried.status_code == 200
    body = retried.json()
    assert body["workflow"]["status"] == "Completed"
    assert body["workflow"]["id"] != workflow_id
    assert body["workflow"]["scheduled_from_id"] == workflow_id
    assert len(body["executions"]) == 2

    # The failed original is retained.
    original = client.get(f"/api/v1/workflows/{workflow_id}")
    assert original.json()["status"] == "Failed"

    # Retrying a completed workflow is refused.
    refused = client.post(f"/api/v1/workflows/{body['workflow']['id']}/retry")
    assert refused.status_code == 400
    assert "only failed workflows" in refused.json()["detail"]


# ----------------------------------------------------------------------
# Execution history + retry
# ----------------------------------------------------------------------
def test_execution_history_filters_and_retry(api) -> None:
    client, _ = api
    denied = client.post(
        "/api/v1/executions/runtime",
        json={"capability": "calculation", "params": {"a": 1, "b": 2}},
    )
    assert denied.status_code == 201
    assert denied.json()["status"] == "failed"
    assert denied.json()["error_code"] == "PERMISSION_DENIED"

    # Filters.
    by_status = client.get("/api/v1/executions/runtime?status=failed")
    assert by_status.status_code == 200
    assert len(by_status.json()) == 1

    by_capability = client.get("/api/v1/executions/runtime?capability=calculation")
    assert by_capability.status_code == 200
    assert len(by_capability.json()) == 1

    # Retry creates a fresh execution (same permissions — still denied,
    # never escalated) and links back to the original.
    retried = client.post(
        f"/api/v1/executions/runtime/{denied.json()['id']}/retry"
    )
    assert retried.status_code == 201
    assert retried.json()["id"] != denied.json()["id"]
    assert retried.json()["status"] == "failed"
    assert retried.json()["error_code"] == "PERMISSION_DENIED"
    assert retried.json()["execution_metadata"]["retried_from"] == denied.json()["id"]

    # The original is still in history.
    history = client.get("/api/v1/executions/runtime")
    assert len(history.json()) == 2


# ----------------------------------------------------------------------
# Deployment readiness
# ----------------------------------------------------------------------
def test_ready_and_health_endpoints(api) -> None:
    client, _ = api

    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["database"] == "healthy"

    health = client.get("/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["goalos"]["status"] == "running"
    assert body["database"]["status"] == "healthy"
    assert "worker" in body
    assert body["worker"]["type"] == "scheduler"
    assert "executions" in body
    assert isinstance(body["executions"]["total"], int)
    integration_names = {item["name"] for item in body["integrations"]["items"]}
    assert "scheduler" in integration_names
