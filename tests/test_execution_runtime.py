"""Service tests for the GoalOS execution runtime.

Covers the persisted capability-execution lifecycle (pending → running →
succeeded/failed), inputs/outputs/errors/timestamps/metadata capture,
honest failure states (missing permission, unconfigured integration,
unregistered capability), restart durability, duplicate prevention, and
approved-workflow execution through the runtime with the real
capability/connector pipelines (hermetic fake transport).

No unavailable integration is ever faked: an unconfigured provider is
persisted as ``failed`` with the INTEGRATION_NOT_CONFIGURED reason.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.permissions import Permission
from app.db.base import Base
from app.db.models.runtime_execution import RuntimeExecutionStatus
from app.integrations.factory import build_default_registry
from app.repositories.agent_repository import AgentRepository
from app.repositories.capability_repository import CapabilityRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.runtime_execution_repository import RuntimeExecutionRepository
from app.repositories.skill_repository import SkillRepository
from app.repositories.workflow_repository import WorkflowRepository
from app.schemas.project import ProjectCreateRequest
from app.schemas.workflow import WorkflowCreateRequest
from app.services.agent_factory import AgentFactoryService
from app.services.capability_service import CapabilityService
from app.services.execution_runtime import ExecutionRuntimeService
from app.services.workflow_service import WorkflowService
from tests.integration_helpers import FakeUrlOpener

SEO_GOAL = (
    "Analyse Organigram's website SEO at https://www.organigram.com."
)


def _session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'runtime.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _capability_service(db) -> CapabilityService:
    return CapabilityService(
        CapabilityRepository(db),
        integration_registry=build_default_registry(session=db),
    )


def _runtime(db, *, capability_service=None) -> ExecutionRuntimeService:
    return ExecutionRuntimeService(
        RuntimeExecutionRepository(db),
        capability_service or _capability_service(db),
        workflow_repository=WorkflowRepository(db),
    )


def _agent_factory(db) -> AgentFactoryService:
    return AgentFactoryService(AgentRepository(db), SkillRepository(db))


def _workflow(db) -> object:
    """Create a project + workflow row (the approved-workflow contract)."""
    project = ProjectRepository(db).create(
        ProjectCreateRequest(
            title="Runtime test project",
            description="Project for execution runtime tests.",
            owner="GoalOS",
            department="Autonomous",
            priority="High",
        )
    )
    workflow = WorkflowRepository(db).create(
        WorkflowCreateRequest(project_id=project.id, name="Runtime test workflow")
    )
    return workflow


# ----------------------------------------------------------------------
# Single capability execution lifecycle
# ----------------------------------------------------------------------
def test_execute_capability_succeeds_and_persists_full_lifecycle(tmp_path: Path) -> None:
    """A permitted capability runs and persists output, timestamps, metadata."""
    factory = _session_factory(tmp_path)
    db = factory()
    runtime = _runtime(db)

    response = runtime.execute(
        "calculation",
        {"a": 40, "b": 2},
        {Permission.EXECUTE_CODE},
        agent_name="calculation-agent",
    )

    assert response.status is RuntimeExecutionStatus.SUCCEEDED
    assert response.output == {"result": 42.0}
    assert response.error is None
    assert response.capability == "calculation"
    assert response.agent_name == "calculation-agent"
    assert response.input == {"a": 40, "b": 2}
    assert response.permissions_required == ["EXECUTE_CODE"]
    assert response.started_at is not None
    assert response.completed_at is not None
    assert response.completed_at >= response.started_at
    assert response.execution_metadata["resolution"]["available"] is True
    assert response.execution_metadata["resolution"]["permissions_sufficient"] is True

    # Persisted, not in-memory: a fresh session sees the same record.
    fresh = factory()
    persisted = RuntimeExecutionRepository(fresh).get(response.id)
    assert persisted is not None
    assert persisted.status is RuntimeExecutionStatus.SUCCEEDED
    assert persisted.output == {"result": 42.0}
    assert persisted.started_at is not None and persisted.completed_at is not None
    fresh.close()
    db.close()


def test_execute_denied_without_permission(tmp_path: Path) -> None:
    """Missing permission is persisted as failed — never implicit escalation."""
    db = _session_factory(tmp_path)()
    runtime = _runtime(db)

    response = runtime.execute("calculation", {"a": 40, "b": 2}, set())

    assert response.status is RuntimeExecutionStatus.FAILED
    assert response.error is not None
    assert "missing required permissions" in response.error
    assert "EXECUTE_CODE" in response.error
    assert response.output is None
    db.close()


def test_execute_unconfigured_integration_is_honest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a search provider web_search reports INTEGRATION_NOT_CONFIGURED."""
    monkeypatch.delenv("GOALOS_SEARCH_PROVIDER", raising=False)
    db = _session_factory(tmp_path)()
    runtime = _runtime(db)

    response = runtime.execute(
        "web_search",
        {"query": "organigram seo"},
        {Permission.READ_WEBSITE},
    )

    assert response.status is RuntimeExecutionStatus.FAILED
    assert response.error is not None
    assert "INTEGRATION_NOT_CONFIGURED" in response.error
    assert "search provider" in response.error
    assert response.execution_metadata["resolution"]["available"] is False
    db.close()


def test_execute_unregistered_capability_fails_honestly(tmp_path: Path) -> None:
    """An unknown capability is failed with a clear reason, never executed."""
    db = _session_factory(tmp_path)()
    runtime = _runtime(db)

    response = runtime.execute("no_such_capability", {}, set())

    assert response.status is RuntimeExecutionStatus.FAILED
    assert response.error == "capability is not registered"
    assert response.started_at is None  # never dispatched
    db.close()


def test_execution_metadata_captures_resolution(tmp_path: Path) -> None:
    """Resolution details (provider, permissions, availability) are persisted."""
    db = _session_factory(tmp_path)()
    runtime = _runtime(db)

    response = runtime.execute(
        "calculation",
        {"a": 1, "b": 2},
        {Permission.EXECUTE_CODE},
        metadata={"source": "test"},
    )

    resolution = response.execution_metadata["resolution"]
    assert resolution["exists"] is True
    assert resolution["enabled"] is True
    assert resolution["provider"] == "native"
    assert response.execution_metadata["source"] == "test"
    db.close()


def test_execution_survives_restart(tmp_path: Path) -> None:
    """A restart (fresh session/repository) never loses execution state."""
    factory = _session_factory(tmp_path)
    db = factory()
    runtime = _runtime(db)
    response = runtime.execute(
        "calculation", {"a": 10, "b": 5}, {Permission.EXECUTE_CODE}
    )
    db.close()

    # Simulate a restart: brand-new session + composition root.
    db2 = factory()
    runtime2 = _runtime(db2)
    restored = runtime2.get(response.id)
    assert restored is not None
    assert restored.status is RuntimeExecutionStatus.SUCCEEDED
    assert restored.output == {"result": 15.0}
    assert restored.capability == "calculation"
    assert restored.started_at is not None
    assert restored.completed_at is not None

    listed = runtime2.list()
    assert [item.id for item in listed] == [response.id]
    db2.close()


# ----------------------------------------------------------------------
# Approved workflow execution
# ----------------------------------------------------------------------
def test_run_workflow_requires_approval(tmp_path: Path) -> None:
    """A workflow without an approved requirement is refused."""
    db = _session_factory(tmp_path)()
    runtime = _runtime(db)
    workflow = _workflow(db)

    with pytest.raises(ValueError, match="not approved"):
        runtime.run_workflow(workflow.id)
    db.close()


def test_run_workflow_requires_permissions_or_agent_factory(tmp_path: Path) -> None:
    """Without explicit permissions and without an agent factory, refused."""
    db = _session_factory(tmp_path)()
    workflow_service = WorkflowService(WorkflowRepository(db), RuntimeExecutionRepository(db))
    workflow = _workflow(db)
    workflow_service.approve(workflow.id, SEO_GOAL, capability_service=_capability_service(db))

    runtime = _runtime(db)
    with pytest.raises(ValueError, match="permissions are required"):
        runtime.run_workflow(workflow.id, requirement=SEO_GOAL)
    db.close()


def test_run_workflow_executes_steps_and_persists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An approved workflow runs each step through the runtime and persists.

    With the search provider configured and the transport faked, the REAL
    web.search and website.crawl pipelines execute hermetically.
    """
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    db = _session_factory(tmp_path)()
    workflow_service = WorkflowService(WorkflowRepository(db), RuntimeExecutionRepository(db))
    workflow = _workflow(db)
    approved = workflow_service.approve(
        workflow.id, SEO_GOAL, capability_service=_capability_service(db)
    )
    assert approved.requirement == SEO_GOAL
    assert approved.resolved_capabilities is not None

    runtime = _runtime(db)
    result = runtime.run_workflow(
        workflow.id, requirement=SEO_GOAL, agent_factory=_agent_factory(db)
    )

    assert result.workflow.status == "Completed"
    assert result.workflow.evaluation["passed"] is True
    assert result.workflow.evaluation["total_steps"] == 2
    steps = {step["capability"]: step for step in result.workflow.steps}
    assert set(steps) == {"keyword_research", "website_analysis"}
    assert all(step["status"] == "Completed" for step in steps.values())
    # The steps ran through the real pipelines.
    assert result.workflow.results["keyword_research"]["source"] == "web.search"
    assert result.workflow.results["website_analysis"]["source"] == "website.crawl"

    # One persisted runtime execution per step, all succeeded.
    assert len(result.executions) == 2
    assert all(
        execution.status is RuntimeExecutionStatus.SUCCEEDED
        for execution in result.executions
    )
    assert {execution.capability for execution in result.executions} == {
        "keyword_research",
        "website_analysis",
    }
    for execution in result.executions:
        assert execution.workflow_id == workflow.id
        assert execution.started_at is not None
        assert execution.completed_at is not None

    # The workflow is now locked — a second run is a duplicate and refused.
    with pytest.raises(ValueError, match="already been run"):
        runtime.run_workflow(workflow.id, requirement=SEO_GOAL)
    db.close()


def test_run_workflow_reports_blocked_integration_honestly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a search provider the workflow fails with the honest reason.

    No step is dispatched and no fabricated result is persisted.
    """
    monkeypatch.delenv("GOALOS_SEARCH_PROVIDER", raising=False)

    db = _session_factory(tmp_path)()
    workflow_service = WorkflowService(WorkflowRepository(db), RuntimeExecutionRepository(db))
    workflow = _workflow(db)
    workflow_service.approve(workflow.id, SEO_GOAL, capability_service=_capability_service(db))

    runtime = _runtime(db)
    result = runtime.run_workflow(
        workflow.id, requirement=SEO_GOAL, agent_factory=_agent_factory(db)
    )

    assert result.workflow.status == "Failed"
    assert result.workflow.evaluation["passed"] is False
    assert "web.search" in (result.workflow.error_message or "")
    blocked_steps = {
        step["capability"]: step for step in result.workflow.steps
    }
    assert blocked_steps["keyword_research"]["status"] == "Blocked"
    # The blocked capability has a persisted BLOCKED runtime execution
    # carrying the honest INTEGRATION_NOT_CONFIGURED reason (never faked).
    assert any(
        execution.capability == "keyword_research"
        and execution.status is RuntimeExecutionStatus.BLOCKED
        and execution.error_code == "INTEGRATION_NOT_CONFIGURED"
        and "web.search" in (execution.error or "")
        for execution in result.executions
    )
    # Nothing was executed: the website step is not in the executions.
    assert not any(
        execution.capability == "website_analysis" for execution in result.executions
    )
    db.close()


def test_run_workflow_executes_capability_directly_with_permissions(tmp_path: Path) -> None:
    """Explicit permissions bypass agent resolution; workflow still completes."""
    db = _session_factory(tmp_path)()
    workflow_service = WorkflowService(WorkflowRepository(db), RuntimeExecutionRepository(db))
    workflow = _workflow(db)
    workflow_service.approve(workflow.id, SEO_GOAL, capability_service=_capability_service(db))

    runtime = _runtime(db)
    result = runtime.run_workflow(
        workflow.id,
        requirement=SEO_GOAL,
        permissions={Permission.READ_WEBSITE},
        agent_name="direct-caller",
    )

    assert result.workflow.status == "Failed"  # web.search unconfigured
    assert "web.search" in (result.workflow.error_message or "")
    db.close()


def test_run_workflow_nonexistent_workflow(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    runtime = _runtime(db)
    with pytest.raises(ValueError, match="workflow not found"):
        runtime.run_workflow(uuid4())
    db.close()


def test_duplicate_active_execution_for_workflow_is_refused(tmp_path: Path) -> None:
    """An in-flight execution for a workflow blocks a second submission."""
    db = _session_factory(tmp_path)()
    runtime = _runtime(db)
    workflow = _workflow(db)

    # Simulate an in-flight execution by inserting a running record.
    repository = RuntimeExecutionRepository(db)
    running = repository.create(
        {
            "workflow_id": workflow.id,
            "capability": "calculation",
            "status": RuntimeExecutionStatus.RUNNING,
            "input": {},
        }
    )
    assert running.status is RuntimeExecutionStatus.RUNNING

    with pytest.raises(ValueError, match="already has an active runtime execution"):
        runtime.execute(
            "calculation",
            {"a": 1, "b": 2},
            {Permission.EXECUTE_CODE},
            workflow_id=workflow.id,
        )
    db.close()
