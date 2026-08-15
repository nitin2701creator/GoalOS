"""API tests for the GoalOS integration execution foundation.

Covers the real API path: integration registry listing/detail, the
health/test operation, honest execution (unconfigured / permission
denied / disabled), execution history, operator enable/disable, and the
task -> integration execution endpoint. No real credentials and no real
network traffic — unconfigured integrations honestly report
INTEGRATION_NOT_CONFIGURED.
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

API_KEY = "goalos-integrations-key"


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """TestClient with an isolated DB; search provider explicitly unset so
    web.search reports INTEGRATION_NOT_CONFIGURED without network access."""
    monkeypatch.setenv("GOALOS_OPENWEBUI_API_KEY", API_KEY)
    monkeypatch.delenv("GOALOS_SEARCH_PROVIDER", raising=False)
    monkeypatch.delenv("GOALOS_TWENTY_BASE_URL", raising=False)
    monkeypatch.delenv("GOALOS_TWENTY_API_KEY", raising=False)
    engine = create_engine(
        f"sqlite:///{tmp_path / 'integrations_api.db'}",
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


def _create_project_with_task(client: TestClient, *, integration: str | None, capability: str | None) -> str:
    project = client.post(
        "/api/v1/projects",
        json={
            "title": "Integration API project",
            "description": "project for integration API tests",
            "owner": "test",
            "department": "Engineering",
            "priority": "high",
        },
    )
    assert project.status_code == 201
    payload = {
        "project_id": project.json()["id"],
        "title": "Integration API task",
        "description": "execute an integration",
        "priority": "high",
    }
    if integration is not None:
        payload["required_integration"] = integration
    if capability is not None:
        payload["required_capability"] = capability
    task = client.post("/api/v1/tasks", json=payload)
    assert task.status_code == 201
    return task.json()["id"]


def test_list_integrations_endpoint(api) -> None:
    """GET /api/v1/integrations lists the persisted registry with state only."""
    response = api.get("/api/v1/integrations")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 9
    by_name = {item["name"]: item for item in body["integrations"]}

    web = by_name["web"]
    assert web["integration_type"] == "web"
    assert web["enabled"] is True
    assert "web.search" in web["capabilities"]
    assert web["registered"] is True
    assert web["status"] in ("Healthy", "Not Configured")

    twenty = by_name["twenty"]
    assert twenty["integration_type"] == "crm"
    assert "GOALOS_TWENTY_API_KEY" in twenty["required_env_vars"]
    assert twenty["status"] == "Not Configured"
    # No secret values are ever exposed.
    payload_text = response.text
    assert "GOALOS_TWENTY_API_KEY=" not in payload_text


def test_detail_and_test_endpoints(api) -> None:
    detail = api.get("/api/v1/integrations/web")
    assert detail.status_code == 200
    assert detail.json()["name"] == "web"

    tested = api.post("/api/v1/integrations/web/test")
    assert tested.status_code == 200
    assert tested.json()["status"] == "Healthy"

    twenty_test = api.post("/api/v1/integrations/twenty/test")
    assert twenty_test.status_code == 200
    assert twenty_test.json()["status"] == "Not Configured"

    missing = api.get("/api/v1/integrations/nope")
    assert missing.status_code == 404


def test_execute_unconfigured_reports_honestly(api) -> None:
    """Unconfigured web.search returns INTEGRATION_NOT_CONFIGURED, never fake data."""
    response = api.post(
        "/api/v1/integrations/web/execute",
        json={"capability": "web.search", "params": {"query": "organigram"}, "permissions": ["READ_WEBSITE"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "INTEGRATION_NOT_CONFIGURED"
    assert body["error_code"] == "INTEGRATION_NOT_CONFIGURED"
    assert "search provider" in (body["error"] or "")
    assert body["execution"] is not None
    assert body["execution"]["status"] == "failed"


def test_execute_permission_denied(api) -> None:
    # web.fetch is available without configuration, so the permission gate
    # fires before any dispatch — no network, honest PERMISSION_DENIED.
    response = api.post(
        "/api/v1/integrations/web/execute",
        json={"capability": "web.fetch", "params": {"url": "https://example.com"}, "permissions": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "PERMISSION_DENIED"
    assert body["error_code"] == "PERMISSION_DENIED"
    assert "READ_WEBSITE" in (body["error"] or "")


def test_disable_integration_via_api(api) -> None:
    disabled = api.patch("/api/v1/integrations/web", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False

    response = api.post(
        "/api/v1/integrations/web/execute",
        json={"capability": "web.search", "permissions": ["READ_WEBSITE"]},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "DISABLED"

    detail = api.get("/api/v1/integrations/web")
    assert detail.json()["enabled"] is False


def test_execution_history_endpoint(api) -> None:
    first = api.post(
        "/api/v1/integrations/web/execute",
        json={"capability": "web.search", "permissions": ["READ_WEBSITE"]},
    )
    assert first.status_code == 200
    api.post(
        "/api/v1/integrations/web/execute",
        json={"capability": "web.fetch", "permissions": ["READ_WEBSITE"]},
    )

    history = api.get("/api/v1/integrations/web/executions")
    assert history.status_code == 200
    body = history.json()
    assert body["total"] >= 2

    filtered = api.get("/api/v1/integrations/web/executions", params={"capability": "web.search"})
    assert filtered.status_code == 200
    assert all(item["capability"] == "web.search" for item in filtered.json()["executions"])

    missing = api.get("/api/v1/integrations/nope/executions")
    assert missing.status_code == 404


def test_task_executes_its_integration_via_api(api) -> None:
    """POST /api/v1/tasks/{id}/integrations/execute runs the task's required
    integration (distinct from the autonomous worker execution endpoint)."""
    task_id = _create_project_with_task(
        api, integration="web", capability="web.search"
    )
    response = api.post(
        f"/api/v1/tasks/{task_id}/integrations/execute",
        json={"params": {"query": "organigram"}, "permissions": ["READ_WEBSITE"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["task"]["status"] == "Failed"
    assert body["task"]["required_integration"] == "web"
    assert body["execution"]["status"] == "INTEGRATION_NOT_CONFIGURED"


def test_task_without_integration_returns_400(api) -> None:
    task_id = _create_project_with_task(api, integration=None, capability=None)
    response = api.post(f"/api/v1/tasks/{task_id}/integrations/execute", json={})
    assert response.status_code == 400
    assert "required integration" in response.json()["detail"]
