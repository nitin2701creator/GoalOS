"""Tests for the ADS development API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_execute_objective_runs_pipeline() -> None:
    """Executing an objective returns a completed run with an audit trail."""

    response = client.post(
        "/api/v1/development/execute",
        json={"objective": "Add analytics module"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["succeeded"] is True
    assert body["objective"] == "Add analytics module"
    assert len(body["tasks"]) == 4
    assert all(task["status"] == "completed" for task in body["tasks"])
    assert len(body["executions"]) == 4
    assert all(execution["verification_passed"] for execution in body["executions"])
    assert all(execution["output"] for execution in body["executions"])


def test_preview_objective_plans_without_executing() -> None:
    """Preview returns a pending plan with no executions."""

    response = client.post(
        "/api/v1/development/preview",
        json={"objective": "Add analytics module"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["succeeded"] is True
    assert len(body["tasks"]) == 4
    assert all(task["status"] == "pending" for task in body["tasks"])
    assert body["executions"] == []


def test_execute_rejects_blank_objective() -> None:
    """A blank objective is rejected by validation."""

    response = client.post("/api/v1/development/execute", json={"objective": ""})

    assert response.status_code == 422


def test_execute_rejects_whitespace_objective() -> None:
    """A whitespace-only objective is rejected by the planner."""

    response = client.post("/api/v1/development/execute", json={"objective": "   "})

    assert response.status_code == 400
    assert "must not be empty" in response.json()["detail"]


def test_execute_with_unavailable_worker_type_blocks_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A requested CLI that is not installed halts with a blocked task."""

    monkeypatch.setattr(
        "app.kernel.development.worker.shutil.which", lambda _: None
    )

    response = client.post(
        "/api/v1/development/execute",
        json={"objective": "Add analytics module", "worker_type": "codex"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["succeeded"] is False
    assert body["tasks"][0]["status"] == "blocked"
    assert body["tasks"][0]["worker"] == "codex"
    assert "unavailable" in body["summary"]
    assert len(body["executions"]) == 1
    assert body["executions"][0]["verification_passed"] is False
