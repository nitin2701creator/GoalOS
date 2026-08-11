"""Tests for the DB-persisted task execution lifecycle."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.execution import Execution, ExecutionStatus
from app.db.models.project import Project
from app.db.models.task import Task
from app.kernel.development.worker import DevelopmentWorker, WorkerResult
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.task_repository import TaskRepository
from app.services.execution_service import ExecutionService


class FailingWorker(DevelopmentWorker):
    """Worker that always fails."""

    def execute(self, prompt: str) -> WorkerResult:
        return WorkerResult(success=False, summary="worker exploded", output="")


class EmptyOutputWorker(DevelopmentWorker):
    """Worker that succeeds but produces no output artifact."""

    def execute(self, prompt: str) -> WorkerResult:
        return WorkerResult(success=True, summary="done", output="   ")


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'lifecycle.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    yield factory
    engine.dispose()


@pytest.fixture
def db(session_factory) -> Session:
    session = session_factory()
    yield session
    session.close()


def _create_project_and_task(db: Session) -> Task:
    project = Project(title="Project", description="desc", owner="o", department="dev", priority="High")
    db.add(project)
    db.commit()
    db.refresh(project)
    task = Task(
        project_id=project.id,
        title="Implement analytics",
        description="Add the analytics module.",
        priority="High",
        status="Draft",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@pytest.fixture
def task(db: Session) -> Task:
    return _create_project_and_task(db)


@pytest.fixture
def service(db: Session) -> ExecutionService:
    return ExecutionService(ExecutionRepository(db), TaskRepository(db))


def test_run_task_persists_completed_execution_and_task_status(service: ExecutionService, task: Task) -> None:
    """A mock run completes and persists result, verification, and status."""

    response = service.run_task(task.id, "mock-worker")

    assert response.status == "Completed"
    assert response.result
    assert response.verification_status == "Passed"
    assert response.verification_summary
    assert response.started_at is not None
    assert response.completed_at is not None

    persisted = service.get(response.id)
    assert persisted is not None
    assert persisted.status == "Completed"
    assert persisted.verification_status == "Passed"

    updated_task = service.task_repository.get(task.id)
    assert updated_task is not None
    assert updated_task.status == "Completed"
    assert updated_task.result == response.result


def test_claim_is_atomic_and_rejects_double_claim(service: ExecutionService, task: Task) -> None:
    """A claimed execution cannot be claimed a second time."""

    from app.schemas.execution import ExecutionCreateRequest

    execution = service.repository.create(
        ExecutionCreateRequest(task_id=task.id, agent_name="worker-a")
    )

    claimed = service.repository.claim(execution.id)
    second = service.repository.claim(execution.id)

    assert claimed is not None
    assert claimed.status == ExecutionStatus.RUNNING
    assert second is None


def test_run_task_rejects_duplicate_active_execution(service: ExecutionService, task: Task) -> None:
    """A task with an in-flight execution cannot be submitted again."""

    from app.schemas.execution import ExecutionCreateRequest

    service.repository.create(ExecutionCreateRequest(task_id=task.id, agent_name="worker-a"))

    with pytest.raises(ValueError, match="already has an active execution"):
        service.run_task(task.id, "worker-b")


def test_run_task_rejects_missing_task(service: ExecutionService) -> None:
    """Executing a nonexistent task fails fast."""

    import uuid

    with pytest.raises(ValueError, match="task not found"):
        service.run_task(uuid.uuid4(), "worker")


def test_run_task_failure_state_is_persisted(service: ExecutionService, task: Task) -> None:
    """A failing worker persists the failure on execution and task."""

    response = service.run_task(task.id, "worker", worker=FailingWorker())

    assert response.status == "Failed"
    assert response.error_message == "worker exploded"
    assert response.verification_status == "Failed"
    assert response.result is not None

    updated_task = service.task_repository.get(task.id)
    assert updated_task is not None
    assert updated_task.status == "Failed"


def test_run_task_verification_failure_is_persisted(service: ExecutionService, task: Task) -> None:
    """A result that fails verification persists the verdict."""

    response = service.run_task(task.id, "worker", worker=EmptyOutputWorker())

    assert response.status == "Failed"
    assert response.verification_status == "Failed"
    assert "no output" in (response.verification_summary or "")
    assert "no output" in (response.error_message or "")

    updated_task = service.task_repository.get(task.id)
    assert updated_task is not None
    assert updated_task.status == "Failed"


def test_run_task_unavailable_cli_worker_persists_failure(
    service: ExecutionService,
    task: Task,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing CLI worker fails the run with a persisted reason."""

    monkeypatch.setattr("app.kernel.development.worker.shutil.which", lambda _: None)

    response = service.run_task(task.id, "worker", worker_type="codex")

    assert response.status == "Failed"
    assert "not installed" in (response.error_message or "")

    updated_task = service.task_repository.get(task.id)
    assert updated_task is not None
    assert updated_task.status == "Failed"


def test_run_task_rejects_unsupported_worker_type(service: ExecutionService, task: Task) -> None:
    """Unknown worker types are rejected before any execution."""

    with pytest.raises(ValueError, match="unsupported worker type"):
        service.run_task(task.id, "worker", worker_type="nope")


def test_restart_does_not_lose_execution_state(session_factory, tmp_path: Path) -> None:
    """A fresh process over the same database sees the persisted lifecycle."""

    session = session_factory()
    task = _create_project_and_task(session)
    service = ExecutionService(ExecutionRepository(session), TaskRepository(session))
    response = service.run_task(task.id, "worker")
    task_id = task.id
    execution_id = response.id
    session.close()

    # Simulate a restart: new session and engine over the same file.
    engine = create_engine(
        f"sqlite:///{tmp_path / 'lifecycle.db'}",
        connect_args={"check_same_thread": False},
    )
    Session2 = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session2 = Session2()
    try:
        restarted_task = session2.get(Task, task_id)
        restarted_execution = session2.get(Execution, execution_id)
        assert restarted_task is not None
        assert restarted_task.status == "Completed"
        assert restarted_execution is not None
        assert restarted_execution.status == ExecutionStatus.COMPLETED
        assert restarted_execution.verification_status == "Passed"
        assert restarted_execution.result
        assert restarted_execution.started_at is not None
        assert restarted_execution.completed_at is not None
    finally:
        session2.close()
        engine.dispose()
