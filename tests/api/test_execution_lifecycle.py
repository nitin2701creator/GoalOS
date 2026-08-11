"""End-to-end tests of the persistent execution lifecycle through the API.

Every step of the acceptance lifecycle is exercised against a temporary
SQLite database: task creation, submission, claiming, execution, result
persistence, verification persistence, final task status, failure states,
duplicate prevention, and restart durability.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import session as session_module
from app.db.base import Base
from app.db.models.execution import Execution, ExecutionStatus
from app.db.models.task import Task
from app.main import app


@pytest.fixture
def api(tmp_path: Path):
    """TestClient whose database dependency points at an isolated file DB."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'e2e.db'}",
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
            yield client, str(tmp_path / "e2e.db")
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _create_goal_project_task(client: TestClient) -> tuple[UUID, UUID, UUID]:
    """Create the goal -> project -> task chain and return their IDs."""
    goal_response = client.post(
        "/api/v1/goals",
        json={
            "title": "Grow revenue",
            "description": "Increase monthly recurring revenue.",
            "executive_owner": "CEO",
            "department": "Sales",
            "priority": "High",
        },
    )
    assert goal_response.status_code == 201
    goal_id = goal_response.json()["id"]

    project_response = client.post(
        "/api/v1/projects",
        json={
            "goal_id": goal_id,
            "title": "Revenue analytics",
            "description": "Analytics for revenue growth.",
            "owner": "Analytics",
            "department": "Sales",
            "priority": "High",
        },
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    task_response = client.post(
        "/api/v1/tasks",
        json={
            "project_id": project_id,
            "title": "Implement revenue dashboard",
            "description": "Build the dashboard module.",
            "priority": "High",
            "status": "Draft",
        },
    )
    assert task_response.status_code == 201
    return goal_id, project_id, task_response.json()["id"]


def test_full_execution_lifecycle_via_api(api) -> None:
    """Goal/task creation through execution, verification, and final state."""
    client, _ = api
    _, _, task_id = _create_goal_project_task(client)

    response = client.post(
        f"/api/v1/tasks/{task_id}/execute",
        json={"agent_name": "mock-worker", "worker_type": "mock"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "Completed"
    assert body["verification_status"] == "Passed"
    assert body["result"]
    assert body["started_at"] is not None
    assert body["completed_at"] is not None
    assert body["execution_duration_seconds"] is not None

    task_response = client.get(f"/api/v1/tasks/{task_id}")
    assert task_response.status_code == 200
    assert task_response.json()["status"] == "Completed"

    # The execution is queryable through its own endpoint.
    executions = client.get(f"/api/v1/tasks/{task_id}/executions")
    assert executions.status_code == 200
    assert len(executions.json()) == 1


def test_execution_failure_is_persisted_via_api(api, monkeypatch: pytest.MonkeyPatch) -> None:
    """An unavailable CLI worker persists a failed execution and task."""
    client, _ = api
    _, _, task_id = _create_goal_project_task(client)

    monkeypatch.setattr("app.kernel.development.worker.shutil.which", lambda _: None)
    response = client.post(
        f"/api/v1/tasks/{task_id}/execute",
        json={"agent_name": "codex-worker", "worker_type": "codex"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "Failed"
    assert "not installed" in body["error_message"]
    assert body["verification_status"] == "Failed"

    task_response = client.get(f"/api/v1/tasks/{task_id}")
    assert task_response.json()["status"] == "Failed"


def test_duplicate_active_execution_is_prevented_via_api(api) -> None:
    """A task with an in-flight execution cannot be submitted again."""
    client, _ = api
    _, _, task_id = _create_goal_project_task(client)

    # Create a pending execution for the task (simulating an in-flight run).
    pending = client.post(
        "/api/v1/executions",
        json={"task_id": task_id, "agent_name": "worker-a"},
    )
    assert pending.status_code == 201
    assert pending.json()["status"] == "Pending"

    response = client.post(
        f"/api/v1/tasks/{task_id}/execute",
        json={"agent_name": "worker-b"},
    )

    assert response.status_code == 400
    assert "already has an active execution" in response.json()["detail"]


def test_restart_does_not_lose_execution_state(api) -> None:
    """Reopening the database shows the full persisted lifecycle."""
    client, db_path = api
    _, _, task_id = _create_goal_project_task(client)

    response = client.post(
        f"/api/v1/tasks/{task_id}/execute",
        json={"agent_name": "mock-worker"},
    )
    assert response.status_code == 201
    execution_id = response.json()["id"]

    # Simulate a restart: fresh engine + session over the same file.
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db: Session = factory()
    try:
        persisted_execution = db.get(Execution, UUID(execution_id))
        persisted_task = db.get(Task, UUID(task_id))
        assert persisted_execution is not None
        assert persisted_execution.status == ExecutionStatus.COMPLETED
        assert persisted_execution.verification_status == "Passed"
        assert persisted_execution.result
        assert persisted_task is not None
        assert persisted_task.status == "Completed"
    finally:
        db.close()
        engine.dispose()
