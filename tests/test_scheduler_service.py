"""Service tests for the GoalOS persisted scheduler and runtime lifecycle.

Covers: schedule create/update/enable/disable/cancel (permission-gated),
due-run execution through the SAME execution runtime as manual runs
(hermetic fake transport), duplicate/in-flight prevention, restart
durability, run-instance history, workflow cancel (in-flight executions
persisted as cancelled), retry of failed executions/workflows, and the
stable failure codes (INTEGRATION_NOT_CONFIGURED, PERMISSION_DENIED,
CAPABILITY_NOT_FOUND, EXECUTION_FAILED). No unavailable integration is
ever faked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agents.permissions import Permission
from app.db.base import Base
from app.db.models.runtime_execution import RuntimeExecutionStatus
from app.integrations.factory import build_default_registry
from app.integrations.scheduler import SchedulerConnector
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
from app.services.execution_runtime import (
    ExecutionRuntimeService,
    RuntimeErrorCode,
)
from app.services.scheduler_service import SchedulerService
from app.services.workflow_service import WorkflowService
from tests.integration_helpers import FakeUrlOpener

SEO_GOAL = "Analyse Organigram's website SEO at https://www.organigram.com."


def _utc(value: datetime | None) -> datetime | None:
    """Treat SQLite's naive datetime reads as UTC for comparisons."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'scheduler_service.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _capability_service(db) -> CapabilityService:
    return CapabilityService(
        CapabilityRepository(db),
        integration_registry=build_default_registry(session=db),
    )


def _build(db) -> tuple[SchedulerService, WorkflowService, WorkflowRepository]:
    capability_service = _capability_service(db)
    workflow_repo = WorkflowRepository(db)
    runtime = ExecutionRuntimeService(
        RuntimeExecutionRepository(db),
        capability_service,
        workflow_repository=workflow_repo,
    )
    agent_factory = AgentFactoryService(AgentRepository(db), SkillRepository(db))
    service = SchedulerService(
        SchedulerConnector(db=db),
        workflow_repo,
        runtime,
        agent_factory,
    )
    workflow_service = WorkflowService(workflow_repo, RuntimeExecutionRepository(db))
    return service, workflow_service, workflow_repo


def _workflow(db) -> object:
    project = ProjectRepository(db).create(
        ProjectCreateRequest(
            title="Scheduler project",
            description="Project for scheduler service tests.",
            owner="GoalOS",
            department="Autonomous",
            priority="High",
        )
    )
    return WorkflowRepository(db).create(
        WorkflowCreateRequest(project_id=project.id, name="Scheduled template")
    )


def _scheduled_template(
    db,
    *,
    requirement: str = SEO_GOAL,
    schedule: str = "daily",
    due: bool = False,
) -> object:
    workflow = _workflow(db)
    workflow_service = WorkflowService(WorkflowRepository(db), RuntimeExecutionRepository(db))
    workflow_service.approve(workflow.id, requirement, capability_service=_capability_service(db))
    SchedulerConnector(db=db).create(workflow.id, schedule, requirement=requirement)
    if due:
        workflow = WorkflowRepository(db).update(
            workflow,
            {"next_run_at": datetime.now(timezone.utc) - timedelta(hours=1)},
        )
    return workflow


# ----------------------------------------------------------------------
# Schedule management
# ----------------------------------------------------------------------
def test_create_schedule_requires_explicit_permission(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    service, _, _ = _build(db)
    workflow = _workflow(db)

    with pytest.raises(ValueError, match="SCHEDULE_WORKFLOWS"):
        service.create_schedule(workflow.id, "daily", requirement=SEO_GOAL)

    with pytest.raises(ValueError, match=RuntimeErrorCode.PERMISSION_DENIED):
        service.create_schedule(
            workflow.id,
            "daily",
            requirement=SEO_GOAL,
            permissions={Permission.READ_ANALYTICS},
        )
    db.close()


def test_schedule_lifecycle_disable_enable_cancel(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    service, _, _ = _build(db)
    workflow = _workflow(db)

    created = service.create_schedule(
        workflow.id,
        "daily",
        requirement=SEO_GOAL,
        permissions={Permission.SCHEDULE_WORKFLOWS},
    )
    assert created["schedule"] == "daily"
    assert created["enabled"] is True
    assert created["next_run_at"] is not None

    # Update = create again (idempotent overwrite).
    updated = service.create_schedule(
        workflow.id,
        "weekly",
        requirement=SEO_GOAL,
        permissions={Permission.SCHEDULE_WORKFLOWS},
    )
    assert updated["schedule"] == "weekly"

    # Disable keeps the definition; enable restores it.
    disabled = service.disable_schedule(workflow.id)
    assert disabled["enabled"] is False
    assert disabled["schedule"] == "weekly"

    enabled = service.enable_schedule(workflow.id)
    assert enabled["enabled"] is True
    assert enabled["schedule"] == "weekly"
    assert enabled["next_run_at"] is not None
    assert _utc(enabled["next_run_at"]) > datetime.now(timezone.utc)

    # Hard cancel clears the schedule definition.
    cancelled = service.cancel_schedule(workflow.id)
    assert cancelled["enabled"] is False
    assert cancelled["schedule"] is None

    # Listing shows only the weekly schedule was one row while active;
    # after cancel there are none.
    listed = service.list_schedules()
    assert listed == []
    db.close()


def test_schedule_survives_restart(tmp_path: Path) -> None:
    factory = _session_factory(tmp_path)
    db = factory()
    _build(db)
    workflow = _scheduled_template(db, schedule="daily")
    db.close()

    db2 = factory()
    service2, _, _ = _build(db2)
    rows = service2.list_schedules()
    assert len(rows) == 1
    assert rows[0]["workflow_id"] == workflow.id
    assert rows[0]["schedule"] == "daily"
    assert rows[0]["enabled"] is True
    db2.close()


# ----------------------------------------------------------------------
# Due-run execution through the runtime
# ----------------------------------------------------------------------
def test_run_due_executes_through_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A due scheduled workflow runs through the REAL pipelines (fake
    transport) as a new run instance with persisted executions."""
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    db = _session_factory(tmp_path)()
    service, _, workflow_repo = _build(db)
    template = _scheduled_template(db, schedule="daily", due=True)

    summary = service.run_due()
    assert summary["due"] == 1
    processed = summary["processed"][0]
    assert processed["status"] == "Completed"
    assert processed["run_workflow_id"]
    assert processed["executions"] == 2

    # The run instance exists, is linked to the template, and succeeded.
    run_id = UUID(processed["run_workflow_id"])
    run = workflow_repo.get(run_id)
    assert run is not None
    assert run.status.value == "Completed"
    assert run.scheduled_from_id == template.id
    assert run.requirement == SEO_GOAL
    assert run.evaluation["passed"] is True

    # One persisted runtime execution per step on the run instance.
    executions = RuntimeExecutionRepository(db).list_by_workflow(run.id)
    assert {execution.capability for execution in executions} == {
        "keyword_research",
        "website_analysis",
    }
    assert all(execution.status is RuntimeExecutionStatus.SUCCEEDED for execution in executions)

    # The template was advanced: not due anymore.
    assert summary["due"] == 1
    refreshed = workflow_repo.get(template.id)
    assert refreshed.next_run_at is not None
    assert _utc(refreshed.next_run_at) > datetime.now(timezone.utc)
    assert refreshed.last_run_at is not None

    # A second tick finds nothing due.
    second = service.run_due()
    assert second["due"] == 0
    db.close()


def test_run_due_fails_honestly_when_integration_unconfigured(tmp_path: Path) -> None:
    """Without a search provider the scheduled run fails honestly (blocked
    step, persisted executions), and the template still advances."""
    db = _session_factory(tmp_path)()
    service, _, workflow_repo = _build(db)
    template = _scheduled_template(db, schedule="daily", due=True)

    summary = service.run_due()
    processed = summary["processed"][0]
    assert processed["status"] == "Failed"
    assert processed["evaluation"]["passed"] is False

    run = workflow_repo.get(UUID(processed["run_workflow_id"]))
    assert run.status.value == "Failed"
    assert "web.search" in (run.error_message or "")

    # The blocked step persisted a BLOCKED execution with the honest code.
    executions = RuntimeExecutionRepository(db).list_by_workflow(run.id)
    blocked = [execution for execution in executions if execution.capability == "keyword_research"]
    assert len(blocked) == 1
    assert blocked[0].status is RuntimeExecutionStatus.BLOCKED
    assert blocked[0].error_code == RuntimeErrorCode.INTEGRATION_NOT_CONFIGURED
    assert "web.search" in (blocked[0].error or "")

    # Template advanced despite the failed run (never wedged).
    refreshed = workflow_repo.get(template.id)
    assert _utc(refreshed.next_run_at) > datetime.now(timezone.utc)
    db.close()


def test_run_due_skips_in_flight_run(tmp_path: Path) -> None:
    """A template with a pending run instance is not cloned again."""
    db = _session_factory(tmp_path)()
    service, _, workflow_repo = _build(db)
    template = _scheduled_template(db, schedule="daily", due=True)

    # Simulate a crash mid-run: a run instance that never finished.
    pending = workflow_repo.create(
        WorkflowCreateRequest(
            project_id=template.project_id,
            name=f"{template.name} · scheduled crash",
        )
    )
    workflow_repo.update(
        pending,
        {"scheduled_from_id": template.id, "requirement": SEO_GOAL},
    )

    summary = service.run_due()
    processed = summary["processed"][0]
    assert processed["status"] == "skipped_in_flight"
    assert "run_workflow_id" not in processed
    db.close()


def test_run_now_manually_triggers_scheduled_workflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    db = _session_factory(tmp_path)()
    service, _, _ = _build(db)
    template = _scheduled_template(db, schedule="daily")  # not due

    result = service.run_now(template.id)
    assert result.workflow.status == "Completed"
    assert result.workflow.scheduled_from_id == template.id
    assert len(result.executions) == 2

    # Non-scheduled workflows are refused.
    plain = _workflow(db)
    with pytest.raises(ValueError, match="not scheduled"):
        service.run_now(plain.id)
    db.close()


def test_run_due_claim_prevents_duplicate_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once claimed, a second worker tick cannot double-run the workflow."""
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())

    db = _session_factory(tmp_path)()
    service, _, workflow_repo = _build(db)
    template = _scheduled_template(db, schedule="daily", due=True)

    # First worker claims the run; the run completes and advances.
    first = service.run_due()
    assert first["processed"][0]["status"] == "Completed"

    # Simulate a second worker racing on the same (stale) due list: the
    # claim fails because next_run_at moved, so nothing runs twice.
    claimed = SchedulerConnector(db=db).claim(
        template.id,
        now=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    assert claimed is False

    runs = workflow_repo.list_runs_of(template.id)
    assert len(runs) == 1
    db.close()


def test_run_due_schedule_persists_across_restart(tmp_path: Path) -> None:
    """Scheduled run history survives an application restart."""
    factory = _session_factory(tmp_path)
    db = factory()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())
    try:
        # Compose AFTER configuring the provider so the registry picks it up.
        service, _, _ = _build(db)
        template = _scheduled_template(db, schedule="daily", due=True)
        summary = service.run_due()
        assert summary["processed"][0]["status"] == "Completed"
    finally:
        monkeypatch.undo()
        db.close()

    db2 = factory()
    service2, _, workflow_repo2 = _build(db2)
    rows = service2.list_schedules()
    assert len(rows) == 1
    assert rows[0]["run_count"] == 1
    assert rows[0]["last_run_status"] == "Completed"
    runs = workflow_repo2.list_runs_of(template.id)
    assert len(runs) == 1
    assert runs[0].status.value == "Completed"
    db2.close()


# ----------------------------------------------------------------------
# Workflow control: cancel + retry
# ----------------------------------------------------------------------
def test_cancel_marks_in_flight_executions_cancelled(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    _, workflow_service, workflow_repo = _build(db)
    workflow = _workflow(db)

    # Simulate an in-flight capability execution for the workflow.
    repository = RuntimeExecutionRepository(db)
    running = repository.create(
        {
            "workflow_id": workflow.id,
            "capability": "calculation",
            "status": RuntimeExecutionStatus.RUNNING,
            "input": {"a": 1, "b": 2},
        }
    )

    workflow_service.cancel(workflow.id)
    # The API endpoint composes workflow cancel + runtime cancel of the
    # in-flight executions; mirror that here.
    runtime = ExecutionRuntimeService(
        RuntimeExecutionRepository(db), _capability_service(db)
    )
    cancelled_runs = runtime.cancel_in_flight(workflow.id)
    assert [item.id for item in cancelled_runs] == [running.id]
    cancelled = RuntimeExecutionRepository(db).get(running.id)
    assert cancelled is not None
    assert cancelled.status is RuntimeExecutionStatus.CANCELLED
    assert cancelled.error_code == "CANCELLED"

    refreshed = workflow_repo.get(workflow.id)
    assert refreshed.status.value == "Cancelled"
    assert refreshed.schedule_enabled is False
    db.close()


def test_retry_failed_execution_uses_same_permissions(tmp_path: Path) -> None:
    """A crashed execution retries with the same granted permissions and
    succeeds against the real runtime."""
    db = _session_factory(tmp_path)()
    capability_service = _capability_service(db)
    repository = RuntimeExecutionRepository(db)

    class _CrashingExecutor:
        def execute(self, capability, params, permissions):
            raise RuntimeError("boom")

    crashed = ExecutionRuntimeService(
        repository, capability_service, executor=_CrashingExecutor()
    ).execute(
        "calculation",
        {"a": 40, "b": 2},
        {Permission.EXECUTE_CODE},
        agent_name="crash-agent",
    )
    assert crashed.status is RuntimeExecutionStatus.FAILED
    assert crashed.error_code == RuntimeErrorCode.EXECUTION_FAILED
    assert "boom" in (crashed.error or "")

    runtime = ExecutionRuntimeService(repository, capability_service)
    retried = runtime.retry(crashed.id)
    assert retried is not None
    assert retried.status is RuntimeExecutionStatus.SUCCEEDED
    assert retried.output == {"result": 42.0}
    assert retried.agent_name == "crash-agent"
    assert retried.execution_metadata["retried_from"] == str(crashed.id)
    # History retained: the original is still there.
    assert RuntimeExecutionRepository(db).get(crashed.id) is not None
    db.close()


def test_retry_refuses_succeeded_execution(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    runtime = ExecutionRuntimeService(
        RuntimeExecutionRepository(db), _capability_service(db)
    )
    execution = runtime.execute(
        "calculation", {"a": 1, "b": 1}, {Permission.EXECUTE_CODE}
    )
    assert execution.status is RuntimeExecutionStatus.SUCCEEDED
    with pytest.raises(ValueError, match="only failed"):
        runtime.retry(execution.id)
    db.close()


def test_retry_failed_workflow_clones_run_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Retry of a failed workflow runs a fresh instance; history retained."""
    db = _session_factory(tmp_path)()
    workflow_repo = WorkflowRepository(db)
    agent_factory = AgentFactoryService(AgentRepository(db), SkillRepository(db))

    workflow = _workflow(db)
    WorkflowService(workflow_repo, RuntimeExecutionRepository(db)).approve(
        workflow.id, SEO_GOAL, capability_service=_capability_service(db)
    )

    # Initial run WITHOUT a search provider fails honestly.
    runtime_no_provider = ExecutionRuntimeService(
        RuntimeExecutionRepository(db),
        _capability_service(db),
        workflow_repository=workflow_repo,
    )
    failed = runtime_no_provider.run_workflow(
        workflow.id, requirement=SEO_GOAL, agent_factory=agent_factory
    )
    assert failed.workflow.status == "Failed"

    # Configure the integration (fresh composition root picks it up), then
    # retry → a fresh completed run instance.
    monkeypatch.setenv("GOALOS_SEARCH_PROVIDER", "duckduckgo")
    monkeypatch.setattr("app.integrations.http_client.urlopen", FakeUrlOpener())
    runtime_with_provider = ExecutionRuntimeService(
        RuntimeExecutionRepository(db),
        _capability_service(db),
        workflow_repository=workflow_repo,
    )
    retried = runtime_with_provider.retry_workflow(
        workflow.id, agent_factory=agent_factory
    )
    assert retried.workflow.status == "Completed"
    assert retried.workflow.id != workflow.id
    assert retried.workflow.scheduled_from_id == workflow.id
    assert retried.workflow.name == f"{workflow.name} · retry"
    assert len(retried.executions) == 2

    # The failed original is untouched (history retained).
    original = workflow_repo.get(workflow.id)
    assert original.status.value == "Failed"

    # Only failed workflows can be retried.
    with pytest.raises(ValueError, match="only failed workflows"):
        runtime_with_provider.retry_workflow(
            retried.workflow.id, agent_factory=agent_factory
        )
    db.close()


# ----------------------------------------------------------------------
# Stable failure codes
# ----------------------------------------------------------------------
def test_stable_error_codes_on_executions(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    runtime = ExecutionRuntimeService(
        RuntimeExecutionRepository(db), _capability_service(db)
    )

    denied = runtime.execute("calculation", {"a": 1, "b": 2}, set())
    assert denied.error_code == RuntimeErrorCode.PERMISSION_DENIED
    assert "missing required permissions" in (denied.error or "")

    missing = runtime.execute("no_such_capability", {}, set())
    assert missing.error_code == RuntimeErrorCode.CAPABILITY_NOT_FOUND
    assert missing.error == "capability is not registered"

    unconfigured = runtime.execute(
        "web_search", {"query": "x"}, {Permission.READ_WEBSITE}
    )
    assert unconfigured.error_code == RuntimeErrorCode.INTEGRATION_NOT_CONFIGURED
    assert "INTEGRATION_NOT_CONFIGURED" in (unconfigured.error or "")
    db.close()


def test_list_filtered_and_stats(tmp_path: Path) -> None:
    db = _session_factory(tmp_path)()
    runtime = ExecutionRuntimeService(
        RuntimeExecutionRepository(db), _capability_service(db)
    )
    runtime.execute("calculation", {"a": 1, "b": 1}, {Permission.EXECUTE_CODE})
    runtime.execute("calculation", {"a": 1, "b": 1}, set())
    runtime.execute("web_search", {"query": "x"}, {Permission.READ_WEBSITE})

    assert len(runtime.list_filtered(status="succeeded")) == 1
    assert len(runtime.list_filtered(status="failed")) == 2
    assert len(runtime.list_filtered(capability="calculation")) == 2
    stats = runtime.stats()
    assert stats["total"] == 3
    assert stats["by_status"] == {"succeeded": 1, "failed": 2}
    assert stats["by_error_code"][RuntimeErrorCode.PERMISSION_DENIED] == 1
    assert stats["by_error_code"][RuntimeErrorCode.INTEGRATION_NOT_CONFIGURED] == 1
    db.close()


# ----------------------------------------------------------------------
# Worker duplicate-loop protection
# ----------------------------------------------------------------------
def test_scheduler_worker_refuses_duplicate_loop() -> None:
    """A second start() in the same process is refused (one loop per
    process), and a disabled worker never starts."""
    import asyncio

    from app.config import RuntimeSettings
    from app.control_loop.scheduler_worker import SchedulerWorker

    disabled = SchedulerWorker(settings=RuntimeSettings(scheduler_enabled=False))
    assert disabled.start() is False
    assert disabled.is_running is False

    async def scenario() -> None:
        worker = SchedulerWorker(
            settings=RuntimeSettings(scheduler_enabled=True, scheduler_interval=60),
            service_factory=lambda: (object(), object()),
        )
        assert worker.start() is True
        assert worker.is_running is True
        # Duplicate start refused (same process, one loop).
        assert worker.start() is False
        assert worker._task is not None
        await worker.stop()
        assert worker.is_running is False
        assert worker._task is None

    asyncio.run(scenario())
