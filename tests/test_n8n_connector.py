"""Tests for the n8n workflow-automation connector.

Covers: provider-not-configured honesty, successful public-API calls over a
mocked HTTP transport (list/get/run/execution), distinct authentication and
rate-limit handling, malformed responses, workflow-not-found errors,
capability permission denial, the APPROVAL_REQUIRED gate for triggering
workflows, and persisted execution results. Never touches a real n8n
instance.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.agents.permissions import Permission
from app.db.base import Base
from app.db.models.goal import Goal
from app.db.models.project import Project
from app.db.models.workflow import Workflow
from app.integrations.connector_health import ConnectorHealthStatus
from app.integrations.connector_registry import ConnectorRegistry
from app.integrations.exceptions import (
    AuthenticationError,
    ConnectorError,
    PermissionDeniedError,
    RateLimitError,
)
from app.integrations.http_client import HttpClient
from app.integrations.n8n import N8NConnector
from app.repositories.capability_repository import CapabilityRepository
from app.repositories.runtime_execution_repository import RuntimeExecutionRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.services.capability_service import CapabilityService
from app.services.execution_runtime import ExecutionRuntimeService
from tests.integration_helpers import FakeResponse

WORKFLOWS_LIST = {
    "data": [
        {
            "id": "wf_1",
            "name": "Supplier Follow-up",
            "active": True,
            "nodes": [],
            "connections": {},
            "settings": {},
        },
        {
            "id": "wf_2",
            "name": "Daily Report",
            "active": False,
            "nodes": [],
            "connections": {},
            "settings": {},
        },
    ],
    "nextCursor": None,
}

WORKFLOW_ONE = {
    "id": "wf_1",
    "name": "Supplier Follow-up",
    "active": True,
    "nodes": [{"id": "webhook_1", "type": "n8n-nodes-base.webhook", "name": "Webhook", "position": [250, 300], "parameters": {"path": "supplier", "httpMethod": "POST"}}],
    "connections": {},
    "settings": {},
}

EXECUTION_RESULT = {
    "id": "exec_1",
    "finished": True,
    "mode": "trigger",
    "status": "success",
    "data": {
        "resultData": {
            "lastNodeExecuted": "HTTP Request",
            "runData": {
                "HTTP Request": {
                    "main": [[{"json": {"statusCode": 200, "body": "ok"}}]],
                }
            },
        }
    },
}


class N8nFakeOpener:
    """Serve n8n-style fixtures and record every request."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request, timeout=None) -> FakeResponse:
        url = str(getattr(request, "full_url", request))
        method = str(getattr(request, "get_method", lambda: "GET")())
        self.calls.append((method, url))
        path = url.split("?", 1)[0]
        if path.endswith("/api/v1/workflows") and method == "GET":
            return FakeResponse(
                json.dumps(WORKFLOWS_LIST).encode(), url, content_type="application/json"
            )
        if "/api/v1/workflows/" in path and path.endswith("/run") and method == "POST":
            return FakeResponse(
                json.dumps({"executionId": "exec_1"}).encode(), url, content_type="application/json"
            )
        if "/api/v1/workflows/" in path and method == "GET":
            return FakeResponse(
                json.dumps(WORKFLOW_ONE).encode(), url, content_type="application/json"
            )
        if "/api/v1/executions/" in path and method == "GET":
            return FakeResponse(
                json.dumps(EXECUTION_RESULT).encode(), url, content_type="application/json"
            )
        return FakeResponse(b"Not Found", url, status=404)


def make_connector(
    opener=None,
    *,
    base_url: str = "https://n8n.example.com",
    api_key: str = "test-key",
):
    return N8NConnector(
        client=HttpClient(opener=opener or N8nFakeOpener()),
        base_url=base_url,
        api_key=api_key,
    )


def test_n8n_requires_base_url_and_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("N8N_BASE_URL", raising=False)
    monkeypatch.delenv("N8N_API_KEY", raising=False)
    monkeypatch.delenv("GOALOS_N8N_BASE_URL", raising=False)
    monkeypatch.delenv("GOALOS_N8N_API_KEY", raising=False)
    partial = N8NConnector(base_url="https://n8n.example.com")
    assert not partial.is_configured
    assert "N8N_API_KEY" in partial.health_check().message


def test_n8n_reports_not_configured_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("N8N_BASE_URL", raising=False)
    monkeypatch.delenv("N8N_API_KEY", raising=False)
    monkeypatch.delenv("GOALOS_N8N_BASE_URL", raising=False)
    monkeypatch.delenv("GOALOS_N8N_API_KEY", raising=False)
    connector = N8NConnector()
    assert connector.health_check().status is ConnectorHealthStatus.NOT_CONFIGURED
    assert not connector.is_configured
    available, reason = connector.capability_available("n8n.list_workflows")
    assert not available
    assert "N8N_BASE_URL" in reason and "N8N_API_KEY" in reason


def test_n8n_list_workflows_parses() -> None:
    opener = N8nFakeOpener()
    connector = make_connector(opener)
    assert connector.is_configured

    result = connector.execute(
        "n8n.list_workflows",
        {"limit": 5},
        permissions={Permission.READ_AUTOMATION},
    )

    assert result["total"] == 2
    assert result["items"][0]["name"] == "Supplier Follow-up"
    method, url = opener.calls[0]
    assert method == "GET"
    assert url.split("?", 1)[0].endswith("/api/v1/workflows")
    assert "limit=5" in url


def test_n8n_get_workflow_parses() -> None:
    opener = N8nFakeOpener()
    connector = make_connector(opener)

    result = connector.execute(
        "n8n.get_workflow",
        {"id": "wf_1"},
        permissions={Permission.READ_AUTOMATION},
    )

    assert result["workflow"]["id"] == "wf_1"
    method, url = opener.calls[0]
    assert method == "GET"
    assert url.endswith("/api/v1/workflows/wf_1")


def test_n8n_run_workflow_returns_execution_result() -> None:
    opener = N8nFakeOpener()
    connector = make_connector(opener)

    result = connector.execute(
        "n8n.run_workflow",
        {"id": "wf_1", "payload": {"supplier": "Organigram"}},
        permissions={Permission.EXECUTE_AUTOMATION},
    )

    assert result["execution_id"] == "exec_1"
    assert result["finished"] is True
    assert result["status"] == "success"
    assert result["last_node"] == "HTTP Request"
    assert result["node_outputs"][0]["output"]["statusCode"] == 200
    methods = [method for method, _ in opener.calls]
    assert methods[0] == "POST"
    assert opener.calls[0][1].endswith("/api/v1/workflows/wf_1/run")
    assert any(url.endswith("/api/v1/executions/exec_1") for _, url in opener.calls)


def test_n8n_auth_failure_is_distinct() -> None:
    def unauthorized(request, timeout=None) -> FakeResponse:
        return FakeResponse(
            b'{"message": "Invalid API Key"}',
            str(request.full_url),
            status=401,
            content_type="application/json",
        )

    connector = make_connector(unauthorized)
    with pytest.raises(AuthenticationError, match="AUTHENTICATION_FAILED"):
        connector.execute(
            "n8n.list_workflows", {}, permissions={Permission.READ_AUTOMATION}
        )


def test_n8n_rate_limit_is_distinct() -> None:
    def limited(request, timeout=None) -> FakeResponse:
        return FakeResponse(
            b'{"message": "Too Many Requests"}',
            str(request.full_url),
            status=429,
            content_type="application/json",
        )

    connector = make_connector(limited)
    with pytest.raises(RateLimitError, match="RATE_LIMITED"):
        connector.execute(
            "n8n.list_workflows", {}, permissions={Permission.READ_AUTOMATION}
        )


def test_n8n_malformed_response_raises_structured_error() -> None:
    def garbage(request, timeout=None) -> FakeResponse:
        return FakeResponse(b"<html>not json</html>", str(request.full_url), content_type="text/html")

    connector = make_connector(garbage)
    with pytest.raises(ConnectorError, match="not valid JSON"):
        connector.execute(
            "n8n.list_workflows", {}, permissions={Permission.READ_AUTOMATION}
        )


def test_n8n_run_without_execution_id_raises() -> None:
    def no_execution_id(request, timeout=None) -> FakeResponse:
        return FakeResponse(b"{}", str(request.full_url), content_type="application/json")

    connector = make_connector(no_execution_id)
    with pytest.raises(ConnectorError, match="executionId"):
        connector.execute(
            "n8n.run_workflow",
            {"id": "wf_1"},
            permissions={Permission.EXECUTE_AUTOMATION},
        )


def test_n8n_workflow_not_found_is_connector_error() -> None:
    def not_found(request, timeout=None) -> FakeResponse:
        return FakeResponse(
            b'{"message": "Workflow with ID \\"wf_99\\" does not exist"}',
            str(request.full_url),
            status=404,
            content_type="application/json",
        )

    connector = make_connector(not_found)
    with pytest.raises(ConnectorError, match="HTTP 404"):
        connector.execute(
            "n8n.run_workflow",
            {"id": "wf_99"},
            permissions={Permission.EXECUTE_AUTOMATION},
        )


def test_n8n_failed_execution_is_not_reported_as_success() -> None:
    """A workflow that finishes with status error raises a structured failure."""
    def failed_execution(request, timeout=None) -> FakeResponse:
        url = str(getattr(request, "full_url", request))
        method = str(getattr(request, "get_method", lambda: "GET")())
        if url.endswith("/api/v1/workflows/wf_1/run") and method == "POST":
            return FakeResponse(
                json.dumps({"executionId": "exec_fail"}).encode(),
                url,
                content_type="application/json",
            )
        payload = {
            "id": "exec_fail",
            "finished": True,
            "status": "error",
            "data": {
                "resultData": {
                    "lastNodeExecuted": "Send Email",
                    "runData": {
                        "Send Email": {
                            "main": [[{"json": {}, "error": "SMTP connection refused"}]],
                        }
                    },
                }
            },
        }
        return FakeResponse(
            json.dumps(payload).encode(), url, content_type="application/json"
        )

    connector = make_connector(failed_execution)
    with pytest.raises(ConnectorError, match="n8n workflow execution failed.*Send Email"):
        connector.execute(
            "n8n.run_workflow",
            {"id": "wf_1"},
            permissions={Permission.EXECUTE_AUTOMATION},
        )


def test_n8n_permission_denial() -> None:
    connector = make_connector()
    with pytest.raises(PermissionDeniedError, match="READ_AUTOMATION"):
        connector.execute("n8n.list_workflows", {}, permissions={Permission.READ_WEBSITE})
    with pytest.raises(PermissionDeniedError, match="EXECUTE_AUTOMATION"):
        connector.execute(
            "n8n.run_workflow",
            {"id": "wf_1"},
            permissions={Permission.READ_AUTOMATION},
        )


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'n8n.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


def _runtime(session: Session, opener) -> ExecutionRuntimeService:
    registry = ConnectorRegistry()
    registry.register(
        N8NConnector(
            client=HttpClient(opener=opener),
            base_url="https://n8n.example.com",
            api_key="test-key",
        )
    )
    capability_service = CapabilityService(CapabilityRepository(session), integration_registry=registry)
    capability_service.ensure_seeded()
    return ExecutionRuntimeService(
        RuntimeExecutionRepository(session),
        capability_service,
        workflow_repository=WorkflowRepository(session),
    )


def test_n8n_execution_result_persisted_via_runtime(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = N8nFakeOpener()
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    session = session_factory()
    try:
        runtime = _runtime(session, opener)
        result = runtime.execute(
            "n8n_list_workflows",
            {"limit": 5},
            {Permission.READ_AUTOMATION},
        )
        assert result.status.value == "succeeded"
        assert result.output["total"] == 2
        persisted = runtime.get(result.id)
        assert persisted is not None
        assert persisted.status.value == "succeeded"
        assert persisted.provider == "n8n"
    finally:
        session.close()


def test_n8n_run_blocked_without_approved_workflow(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Triggering a workflow never runs silently: direct execution is APPROVAL_REQUIRED."""
    opener = N8nFakeOpener()
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    session = session_factory()
    try:
        runtime = _runtime(session, opener)
        result = runtime.execute(
            "n8n_run_workflow",
            {"id": "wf_1", "payload": {"supplier": "Organigram"}},
            {Permission.EXECUTE_AUTOMATION},
        )
        assert result.status.value == "blocked"
        assert result.error_code == "APPROVAL_REQUIRED"
        assert "APPROVAL_REQUIRED" in (result.error or "")
    finally:
        session.close()


def test_n8n_run_allowed_inside_approved_workflow(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same workflow trigger runs inside an approved workflow."""
    opener = N8nFakeOpener()
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    session = session_factory()
    try:
        goal = Goal(title="Ops", description="d", executive_owner="COO", department="Operations", priority="High")
        session.add(goal)
        session.commit()
        session.refresh(goal)
        project = Project(goal_id=goal.id, title="p", description="d", owner="o", department="Operations", priority="High")
        session.add(project)
        session.commit()
        session.refresh(project)
        workflow = Workflow(project_id=project.id, name="Approved workflow")
        session.add(workflow)
        session.commit()
        session.refresh(workflow)
        workflow = WorkflowRepository(session).update(workflow, {"requirement": "Run supplier follow-up workflow"})

        runtime = _runtime(session, opener)
        result = runtime.execute(
            "n8n_run_workflow",
            {"id": "wf_1", "payload": {"supplier": "Organigram"}},
            {Permission.EXECUTE_AUTOMATION},
            workflow_id=workflow.id,
        )
        assert result.status.value == "succeeded"
        assert result.output["execution_id"] == "exec_1"
        assert result.output["node_outputs"][0]["output"]["statusCode"] == 200
    finally:
        session.close()
