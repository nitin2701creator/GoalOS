"""API tests for the autonomous execution endpoint.

``POST /api/v1/tasks/{task_id}/autonomous-execute`` runs the loop through
the real API path: task submission, atomic claiming, repository
inspection, real ``python -m pytest`` subprocess runs, bounded retries,
and full persistence of state, attempts, test results, errors, review
results, and the final result.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import session as session_module
from app.db.base import Base
from app.main import app


@pytest.fixture
def api(tmp_path: Path):
    """TestClient whose database dependency points at an isolated file DB."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'autonomous-api.db'}",
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


def test_autonomous_execution_via_api_persists_bounded_failure(
    api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run against a failing suite burns its bounded attempts and persists."""
    client = api
    _, _, task_id = _create_goal_project_task(client)

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "test_always_fails.py").write_text(
        "def test_always_fails():\n    assert False\n"
    )
    monkeypatch.setenv("GOALOS_REPOSITORY", str(repo))

    response = client.post(
        f"/api/v1/tasks/{task_id}/autonomous-execute",
        json={"agent_name": "ads-worker", "worker_type": "mock"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "Failed"
    assert body["state"] == "FAILED"
    assert body["attempts"] == 3  # default bounded retry limit
    assert body["commit_hash"] is None
    assert body["verification_status"] == "Failed"
    assert "tests failed" in (body["errors"] or "")
    assert "maximum attempts reached" in (body["error_message"] or "")
    assert body["test_results"]  # every pytest run is persisted
    assert body["result"]  # the worker output is persisted

    task_response = client.get(f"/api/v1/tasks/{task_id}")
    assert task_response.status_code == 200
    assert task_response.json()["status"] == "Failed"

    executions = client.get(f"/api/v1/tasks/{task_id}/executions")
    assert executions.status_code == 200
    assert len(executions.json()) == 1


def test_autonomous_execution_via_api_native_executor_fails_honestly(
    api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The native executor path is wired through the API and never fakes success.

    With the default placeholder provider (no real LLM configured), the
    native executor must fail honestly and persist the failure rather
    than returning a fabricated implementation.
    """
    client = api
    _, _, task_id = _create_goal_project_task(client)

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "test_always_fails.py").write_text(
        "def test_always_fails():\n    assert False\n"
    )
    monkeypatch.setenv("GOALOS_REPOSITORY", str(repo))

    response = client.post(
        f"/api/v1/tasks/{task_id}/autonomous-execute",
        json={"agent_name": "native", "worker_type": "mock", "executor": "native"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "Failed"
    assert body["state"] == "FAILED"
    assert body["commit_hash"] is None
    assert "native executor" in (body["errors"] or "")
    assert body["attempts"] > 0
    assert body["test_results"]  # the loop still persisted its test runs

    task_response = client.get(f"/api/v1/tasks/{task_id}")
    assert task_response.json()["status"] == "Failed"


def test_autonomous_execution_via_api_rejects_unsupported_executor(api) -> None:
    """An unknown executor name is rejected with a 400 before any run."""
    client = api
    _, _, task_id = _create_goal_project_task(client)

    response = client.post(
        f"/api/v1/tasks/{task_id}/autonomous-execute",
        json={"agent_name": "x", "executor": "bogus"},
    )

    assert response.status_code == 400
    assert "unsupported coding executor" in response.json()["detail"]


def test_autonomous_execution_via_api_rejects_duplicate_run(api) -> None:
    """A task with an in-flight execution rejects a second autonomous run."""
    client = api
    _, _, task_id = _create_goal_project_task(client)

    pending = client.post(
        "/api/v1/executions",
        json={"task_id": task_id, "agent_name": "worker-a"},
    )
    assert pending.status_code == 201

    response = client.post(
        f"/api/v1/tasks/{task_id}/autonomous-execute",
        json={"agent_name": "worker-b"},
    )

    assert response.status_code == 400
    assert "already has an active execution" in response.json()["detail"]
