"""Tests for the Twenty CRM connector and its execution-runtime integration.

Covers: provider-not-configured honesty, successful REST calls over a
mocked HTTP transport, distinct authentication-failure and rate-limit
handling, malformed-response errors, capability permission denial, the
APPROVAL_REQUIRED gate for external writes, and persisted execution
results. Never touches the real Twenty service.
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
from app.integrations.twenty import TwentyConnector
from app.repositories.capability_repository import CapabilityRepository
from app.repositories.runtime_execution_repository import RuntimeExecutionRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.services.capability_service import CapabilityService
from app.services.execution_runtime import ExecutionRuntimeService
from tests.integration_helpers import FakeResponse

PEOPLE_LIST = {
    "data": [
        {"id": "p1", "firstName": "Alice", "lastName": "Doe", "email": "alice@example.com"},
        {"id": "p2", "firstName": "Bob", "lastName": "Smith", "email": "bob@example.com"},
    ],
    "totalCount": 2,
}

PERSON_CREATED = {"data": {"id": "p9", "firstName": "Carol", "lastName": "Wong"}}


class TwentyFakeOpener:
    """Serve Twenty-style fixtures and record every request."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request, timeout=None) -> FakeResponse:
        url = str(getattr(request, "full_url", request))
        method = str(getattr(request, "get_method", lambda: "GET")())
        self.calls.append((method, url))
        if url.endswith("/rest/people") and method == "POST":
            return FakeResponse(json.dumps(PERSON_CREATED).encode(), url, content_type="application/json")
        if "/rest/people" in url and method == "PATCH":
            return FakeResponse(json.dumps(PERSON_CREATED).encode(), url, content_type="application/json")
        return FakeResponse(json.dumps(PEOPLE_LIST).encode(), url, content_type="application/json")


def make_connector(opener=None, *, base_url: str = "https://api.twenty.test", api_key: str = "test-key"):
    return TwentyConnector(
        client=HttpClient(opener=opener or TwentyFakeOpener()),
        base_url=base_url,
        api_key=api_key,
    )


def test_twenty_requires_base_url_and_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOALOS_TWENTY_BASE_URL", raising=False)
    monkeypatch.delenv("GOALOS_TWENTY_API_KEY", raising=False)
    partial = TwentyConnector(base_url="https://api.twenty.test")
    assert not partial.is_configured
    assert "GOALOS_TWENTY_API_KEY" in partial.health_check().message


def test_twenty_reports_not_configured_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GOALOS_TWENTY_BASE_URL", raising=False)
    monkeypatch.delenv("GOALOS_TWENTY_API_KEY", raising=False)
    connector = TwentyConnector()
    assert connector.health_check().status is ConnectorHealthStatus.NOT_CONFIGURED
    assert not connector.is_configured
    available, reason = connector.capability_available("twenty.search_people")
    assert not available
    assert "GOALOS_TWENTY_BASE_URL" in reason and "GOALOS_TWENTY_API_KEY" in reason


def test_twenty_search_people_parses_list() -> None:
    opener = TwentyFakeOpener()
    connector = make_connector(opener)
    assert connector.is_configured

    result = connector.execute(
        "twenty.search_people",
        {"query": "alice", "limit": 5},
        permissions={Permission.READ_CRM},
    )

    assert result["object"] == "people"
    assert result["total"] == 2
    assert result["items"][0]["email"] == "alice@example.com"
    method, url = opener.calls[0]
    assert method == "GET"
    assert "filter=" in url and "limit=5" in url


def test_twenty_create_person_posts_fields() -> None:
    opener = TwentyFakeOpener()
    connector = make_connector(opener)

    result = connector.execute(
        "twenty.create_person",
        {"fields": {"firstName": "Carol", "lastName": "Wong", "email": "carol@example.com"}},
        permissions={Permission.WRITE_CRM},
    )

    assert result["created"] is True
    assert result["data"]["id"] == "p9"
    method, url = opener.calls[0]
    assert method == "POST"
    assert url.endswith("/rest/people")


def test_twenty_update_company_patches_by_id() -> None:
    opener = TwentyFakeOpener()
    connector = make_connector(opener)

    result = connector.execute(
        "twenty.update_company",
        {"id": "c1", "fields": {"name": "Organigram"}},
        permissions={Permission.WRITE_CRM},
    )

    assert result["updated"] is True
    assert result["id"] == "c1"
    method, url = opener.calls[0]
    assert method == "PATCH"
    assert url.endswith("/rest/companies/c1")


def test_twenty_auth_failure_is_distinct() -> None:
    def unauthorized(request, timeout=None) -> FakeResponse:
        return FakeResponse(b'{"error": {"message": "invalid api key"}}', str(request.full_url), status=401, content_type="application/json")

    connector = make_connector(unauthorized)
    with pytest.raises(AuthenticationError, match="AUTHENTICATION_FAILED"):
        connector.execute("twenty.search_people", {}, permissions={Permission.READ_CRM})


def test_twenty_rate_limit_is_distinct() -> None:
    def limited(request, timeout=None) -> FakeResponse:
        return FakeResponse(b'{"error": {"message": "rate limited"}}', str(request.full_url), status=429, content_type="application/json")

    connector = make_connector(limited)
    with pytest.raises(RateLimitError, match="RATE_LIMITED"):
        connector.execute("twenty.search_people", {}, permissions={Permission.READ_CRM})


def test_twenty_malformed_response_raises_structured_error() -> None:
    def garbage(request, timeout=None) -> FakeResponse:
        return FakeResponse(b"<html>not json</html>", str(request.full_url), content_type="text/html")

    connector = make_connector(garbage)
    with pytest.raises(ConnectorError, match="not valid JSON"):
        connector.execute("twenty.search_people", {}, permissions={Permission.READ_CRM})


def test_twenty_permission_denial() -> None:
    connector = make_connector()
    with pytest.raises(PermissionDeniedError, match="READ_CRM"):
        connector.execute("twenty.search_people", {}, permissions={Permission.READ_WEBSITE})
    with pytest.raises(PermissionDeniedError, match="WRITE_CRM"):
        connector.execute(
            "twenty.create_person",
            {"fields": {"firstName": "Carol"}},
            permissions={Permission.READ_CRM},
        )


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'twenty.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


def _runtime(session: Session, opener) -> ExecutionRuntimeService:
    registry = ConnectorRegistry()
    registry.register(
        TwentyConnector(
            client=HttpClient(opener=opener),
            base_url="https://api.twenty.test",
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


def test_twenty_execution_result_persisted_via_runtime(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    opener = TwentyFakeOpener()
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    session = session_factory()
    try:
        runtime = _runtime(session, opener)
        result = runtime.execute(
            "twenty_search_people",
            {"query": "alice"},
            {Permission.READ_CRM},
        )
        assert result.status.value == "succeeded"
        assert result.output["total"] == 2
        persisted = runtime.get(result.id)
        assert persisted is not None
        assert persisted.status.value == "succeeded"
        assert persisted.provider == "twenty"
    finally:
        session.close()


def test_twenty_write_blocked_without_approved_workflow(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """External writes never run silently: direct execution is APPROVAL_REQUIRED."""
    opener = TwentyFakeOpener()
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    session = session_factory()
    try:
        runtime = _runtime(session, opener)
        result = runtime.execute(
            "twenty_create_person",
            {"fields": {"firstName": "Carol"}},
            {Permission.WRITE_CRM},
        )
        assert result.status.value == "blocked"
        assert result.error_code == "APPROVAL_REQUIRED"
        assert "APPROVAL_REQUIRED" in (result.error or "")
    finally:
        session.close()


def test_twenty_write_allowed_inside_approved_workflow(
    session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same write runs inside an approved workflow (requirement set)."""
    opener = TwentyFakeOpener()
    monkeypatch.setattr("app.integrations.http_client.urlopen", opener)
    session = session_factory()
    try:
        goal = Goal(title="CRM", description="d", executive_owner="COO", department="Sales", priority="High")
        session.add(goal)
        session.commit()
        session.refresh(goal)
        project = Project(goal_id=goal.id, title="p", description="d", owner="o", department="Sales", priority="High")
        session.add(project)
        session.commit()
        session.refresh(project)
        workflow = Workflow(project_id=project.id, name="Approved workflow")
        session.add(workflow)
        session.commit()
        session.refresh(workflow)
        workflow = WorkflowRepository(session).update(workflow, {"requirement": "Create CRM contacts"})

        runtime = _runtime(session, opener)
        result = runtime.execute(
            "twenty_create_person",
            {"fields": {"firstName": "Carol"}},
            {Permission.WRITE_CRM},
            workflow_id=workflow.id,
        )
        assert result.status.value == "succeeded"
        assert result.output["data"]["id"] == "p9"
    finally:
        session.close()
