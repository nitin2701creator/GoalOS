"""Tests for the GoalOS integration execution foundation.

Covers the persisted integration registry (registration/discovery,
enabled state, config references, health snapshots), execution through
the existing connectors with full persistence, the task -> integration
execution path, execution history, and every honest failure mode
(missing configuration, disabled, invalid integration, permission
denial, authentication failure, rate limiting, connector crash).

External services run through mocks/fakes — no real credentials and no
real network traffic.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import ClassVar

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.permissions import Permission
from app.db.base import Base
from app.integrations.connector_registry import ConnectorRegistry
from app.integrations.exceptions import (
    AuthenticationError,
    RateLimitError,
)
from app.integrations.http_client import HttpClient
from app.integrations.integration_connector import IntegrationConnector
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.project import ProjectCreateRequest
from app.schemas.task import TaskCreateRequest
from app.services.integration_service import IntegrationService
from app.services.task_service import TaskService
from tests.integration_helpers import make_fake_opener


class EchoConnector(IntegrationConnector):
    """Hermetic test connector whose dispatch mirrors provider failures."""

    required_env_vars: tuple[str, ...] = ()
    CAPABILITY_PERMISSIONS: ClassVar[dict[str, Permission]] = {
        "echo.search": Permission.READ_WEBSITE
    }

    def __init__(self, behavior: str = "ok") -> None:
        super().__init__(name="echo", description="Test echo integration")
        self.behavior = behavior

    def _capabilities(self) -> tuple[str, ...]:
        return ("echo.search",)

    def _dispatch(self, capability: str, params: dict) -> dict:
        if capability != "echo.search":
            raise ValueError(f"unsupported capability: {capability}")
        if self.behavior == "auth_error":
            raise AuthenticationError("AUTHENTICATION_FAILED: bad credentials")
        if self.behavior == "rate_limited":
            raise RateLimitError("RATE_LIMITED: too many requests")
        if self.behavior == "boom":
            raise RuntimeError("connector crashed")
        return {"echoed": params.get("text", "")}


def _session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'integrations.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _default_service(db, *, monkeypatch: pytest.MonkeyPatch | None = None):
    """IntegrationService over the real connector registry (hermetic HTTP)."""
    if monkeypatch is not None:
        monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
        monkeypatch.delenv("GOALOS_TWENTY_BASE_URL", raising=False)
        monkeypatch.delenv("GOALOS_TWENTY_API_KEY", raising=False)
    client = HttpClient(opener=make_fake_opener())
    return IntegrationService(db, client=client)


def _echo_service(db, behavior: str = "ok") -> IntegrationService:
    registry = ConnectorRegistry()
    registry.register(EchoConnector(behavior))
    service = IntegrationService(db, registry=registry)
    service.sync()
    return service


def _task_for(db, *, integration: str, capability: str) -> uuid.UUID:
    project = ProjectRepository(db).create(
        ProjectCreateRequest(
            title="Integration project",
            description="project for integration execution tests",
            owner="test",
            department="Engineering",
            priority="high",
        )
    )
    task = TaskRepository(db).create(
        TaskCreateRequest(
            project_id=project.id,
            title="Integration task",
            description="execute an integration",
            priority="high",
            required_integration=integration,
            required_capability=capability,
        )
    )
    return task.id


# ----------------------------------------------------------------------
# Registration / discovery
# ----------------------------------------------------------------------
def test_registration_discovery_and_sync_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _session_factory(tmp_path)()
    service = _default_service(db, monkeypatch=monkeypatch)

    integrations = service.sync()
    assert len(integrations) >= 9
    by_name = {item["name"]: item for item in integrations}

    web = by_name["web"]
    assert web["integration_type"] == "web"
    assert web["enabled"] is True
    assert "web.search" in web["capabilities"]
    assert "web.fetch" in web["capabilities"]

    twenty = by_name["twenty"]
    assert twenty["integration_type"] == "crm"
    assert "GOALOS_TWENTY_BASE_URL" in twenty["required_env_vars"]
    assert "GOALOS_TWENTY_API_KEY" in twenty["required_env_vars"]
    # Config references are names, never values.
    assert all(not value or value.isupper() for value in twenty["required_env_vars"])

    # Sync is idempotent and preserves operator-set enabled state.
    service.set_enabled("web", False)
    synced_again = service.sync()
    assert len(synced_again) == len(integrations)
    assert {item["name"] for item in synced_again} == {item["name"] for item in integrations}
    assert next(item for item in synced_again if item["name"] == "web")["enabled"] is False


def test_get_and_set_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _session_factory(tmp_path)()
    service = _default_service(db, monkeypatch=monkeypatch)
    service.sync()

    detail = service.get("web")
    assert detail is not None
    assert detail["registered"] is True

    disabled = service.set_enabled("web", False)
    assert disabled is not None
    assert disabled["enabled"] is False

    reenabled = service.set_enabled("web", True)
    assert reenabled is not None
    assert reenabled["enabled"] is True

    assert service.set_enabled("nope", True) is None


# ----------------------------------------------------------------------
# Health / test
# ----------------------------------------------------------------------
def test_health_check_reports_configured_and_caches_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _session_factory(tmp_path)()
    service = _default_service(db, monkeypatch=monkeypatch)
    service.sync()

    web = service.test("web")
    assert web is not None
    assert web.status == "Healthy"
    assert web.last_checked_at is not None

    twenty = service.test("twenty")
    assert twenty is not None
    assert twenty.status == "Not Configured"
    assert "GOALOS_TWENTY_BASE_URL" in (twenty.message or "")

    # The snapshot is cached on the persisted row.
    row = service.repository.get_by_name("twenty")
    assert row is not None
    assert row.last_health_status == "Not Configured"
    assert row.last_checked_at is not None

    assert service.test("nope") is None


# ----------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------
def test_successful_execution_is_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = _session_factory(tmp_path)()
    service = _default_service(db, monkeypatch=monkeypatch)
    service.sync()

    response = service.execute(
        "web",
        "web.search",
        {"query": "organigram"},
        [Permission.READ_WEBSITE],
    )
    assert response.status == "OK"
    assert response.result is not None
    assert response.result["provider"] == "duckduckgo"
    assert response.result["result_count"] >= 1
    assert response.error is None

    execution = response.execution
    assert execution is not None
    assert execution.status.value == "succeeded"
    assert execution.provider == "web"
    assert execution.capability == "web.search"
    assert execution.error_code is None
    assert execution.output == response.result


def test_execution_failure_persists_structured_error(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    service = _echo_service(db, behavior="boom")

    response = service.execute("echo", "echo.search", {"text": "hi"}, [Permission.READ_WEBSITE])
    assert response.status == "ERROR"
    assert response.error_code == "EXECUTION_FAILED"
    assert "connector crashed" in (response.error or "")
    assert response.execution is not None
    assert response.execution.status.value == "failed"
    assert response.execution.error_code == "EXECUTION_FAILED"


def test_authentication_failure_is_distinct(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    service = _echo_service(db, behavior="auth_error")

    response = service.execute("echo", "echo.search", {"text": "hi"}, [Permission.READ_WEBSITE])
    assert response.status == "AUTHENTICATION_FAILED"
    assert response.error_code == "AUTHENTICATION_FAILED"
    assert response.execution is not None
    assert response.execution.error_code == "AUTHENTICATION_FAILED"


def test_rate_limiting_is_distinct(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    service = _echo_service(db, behavior="rate_limited")

    response = service.execute("echo", "echo.search", {"text": "hi"}, [Permission.READ_WEBSITE])
    assert response.status == "RATE_LIMITED"
    assert response.error_code == "RATE_LIMITED"
    assert response.execution is not None
    assert response.execution.error_code == "RATE_LIMITED"


def test_permission_denial_is_honest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _session_factory(tmp_path)()
    service = _default_service(db, monkeypatch=monkeypatch)
    service.sync()

    response = service.execute("web", "web.search", {"query": "x"}, [])
    assert response.status == "PERMISSION_DENIED"
    assert response.error_code == "PERMISSION_DENIED"
    assert "READ_WEBSITE" in (response.error or "")
    assert response.execution is not None
    assert response.execution.status.value == "failed"


def test_missing_configuration_reports_integration_not_configured(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    service = _default_service(db)
    service.sync()

    # No GOALOS_SEARCH_PROVIDER -> web.search has no provider.
    response = service.execute("web", "web.search", {"query": "x"}, [Permission.READ_WEBSITE])
    assert response.status == "INTEGRATION_NOT_CONFIGURED"
    assert response.error_code == "INTEGRATION_NOT_CONFIGURED"
    assert "search provider" in (response.error or "")
    assert response.execution is not None
    assert response.execution.status.value == "failed"
    assert response.execution.error_code == "INTEGRATION_NOT_CONFIGURED"


def test_disabled_integration_never_executes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db = _session_factory(tmp_path)()
    service = _default_service(db, monkeypatch=monkeypatch)
    service.sync()
    service.set_enabled("web", False)

    response = service.execute(
        "web", "web.search", {"query": "x"}, [Permission.READ_WEBSITE]
    )
    assert response.status == "DISABLED"
    assert response.error_code == "DISABLED"
    assert "disabled" in (response.error or "")
    assert response.execution is not None
    assert response.execution.status.value == "failed"
    assert response.execution.error_code == "DISABLED"


def test_invalid_integration_reports_not_found(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    service = _echo_service(db)

    response = service.execute("nope", "echo.search", {"text": "hi"}, [Permission.READ_WEBSITE])
    assert response.status == "INTEGRATION_NOT_FOUND"
    assert response.error_code == "INTEGRATION_NOT_FOUND"
    assert response.execution is not None
    assert response.execution.provider == "nope"
    assert response.execution.error_code == "INTEGRATION_NOT_FOUND"


# ----------------------------------------------------------------------
# Execution history
# ----------------------------------------------------------------------
def test_execution_history_is_persisted_and_filterable(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    service = _echo_service(db, behavior="ok")

    service.execute("echo", "echo.search", {"text": "one"}, [Permission.READ_WEBSITE])
    service.execute("echo", "echo.search", {"text": "two"}, [Permission.READ_WEBSITE])

    history = service.execution_history("echo")
    assert len(history) == 2
    assert all(execution.provider == "echo" for execution in history)
    assert all(execution.status.value == "succeeded" for execution in history)

    filtered = service.execution_history("echo", capability="echo.search")
    assert len(filtered) == 2
    assert service.execution_history("echo", capability="other") == []


# ----------------------------------------------------------------------
# Task -> integration execution
# ----------------------------------------------------------------------
def test_task_executes_its_required_integration(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    integration_service = _echo_service(db, behavior="ok")
    task_service = TaskService(TaskRepository(db))

    task_id = _task_for(db, integration="echo", capability="echo.search")
    result = task_service.execute_integration(
        task_id,
        {"text": "hello"},
        [Permission.READ_WEBSITE],
        integration_service,
    )
    assert result is not None
    task = result["task"]
    assert task.status == "Completed"
    assert "hello" in (task.result or "")
    execution = result["execution"]
    assert execution.status == "OK"
    assert execution.execution is not None
    assert execution.execution.status.value == "succeeded"


def test_failed_task_execution_marks_task_failed(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    integration_service = _echo_service(db, behavior="boom")
    task_service = TaskService(TaskRepository(db))

    task_id = _task_for(db, integration="echo", capability="echo.search")
    result = task_service.execute_integration(
        task_id,
        {"text": "hello"},
        [Permission.READ_WEBSITE],
        integration_service,
    )
    assert result is not None
    assert result["task"].status == "Failed"
    assert "connector crashed" in (result["task"].result or "")
    assert result["execution"].status == "ERROR"


def test_task_without_integration_is_refused(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    integration_service = _echo_service(db)
    task_service = TaskService(TaskRepository(db))

    project = ProjectRepository(db).create(
        ProjectCreateRequest(
            title="P", description="d", owner="o", department="Engineering", priority="high"
        )
    )
    task = TaskRepository(db).create(
        TaskCreateRequest(
            project_id=project.id, title="T", description="d", priority="high"
        )
    )
    with pytest.raises(ValueError, match="required integration"):
        task_service.execute_integration(
            task.id, {}, [], integration_service
        )

    assert task_service.execute_integration(uuid.uuid4(), {}, [], integration_service) is None
