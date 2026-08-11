"""Tests for the DB-persisted autonomous execution lifecycle.

``ExecutionService.run_autonomous`` drives the kernel loop and persists
every state transition and artifact on the execution record: current
state, attempts, test results, errors, review results, final result, and
the verification-gated commit hash. These tests exercise that persistence
against a real temporary SQLite database and a real git repository.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models.execution import Execution
from app.db.models.project import Project
from app.db.models.task import Task
from app.kernel.development.autonomous import AutonomousState
from app.kernel.development.executors import NativeGoalOSCodingExecutor
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.task_repository import TaskRepository
from app.services.execution_service import ExecutionService
from tests.kernel.development.helpers import (
    DeterministicEditProvider,
    ScriptedWorker,
    calculator_plan,
    make_calculator_repo,
    write_broken_calculator,
    write_calculator,
)

OBJECTIVE = "Make calculator.add return the sum of its arguments."


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'autonomous.db'}",
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


def _create_task(db: Session) -> Task:
    """Create a project and task in the database."""
    project = Project(
        title="Project",
        description="desc",
        owner="o",
        department="dev",
        priority="High",
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    task = Task(
        project_id=project.id,
        title="Implement calculator sum",
        description=OBJECTIVE,
        priority="High",
        status="Draft",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@pytest.fixture
def service(db: Session) -> ExecutionService:
    return ExecutionService(ExecutionRepository(db), TaskRepository(db))


def test_run_autonomous_persists_completed_execution_state(
    db: Session, service: ExecutionService, tmp_path: Path
) -> None:
    """A successful loop persists state, attempts, artifacts, and commit."""
    task = _create_task(db)
    repo = make_calculator_repo(tmp_path / "repo")
    worker = ScriptedWorker(repo, [write_calculator])

    response = service.run_autonomous(task.id, "ads-worker", worker=worker, repository=repo)

    assert response.status == "Completed"
    assert response.state == AutonomousState.COMPLETED.value
    assert response.attempts == 1
    assert response.commit_hash
    assert response.result
    assert response.verification_status == "Passed"
    assert response.verification_summary

    persisted = service.get(response.id)
    assert persisted is not None
    assert persisted.state == "COMPLETED"
    assert persisted.attempts == 1
    assert persisted.commit_hash == response.commit_hash

    test_results = json.loads(persisted.test_results or "[]")
    assert len(test_results) == 1
    assert test_results[0]["passed"] is True
    assert test_results[0]["command"] == "python -m pytest"

    review_results = json.loads(persisted.review_results or "[]")
    assert len(review_results) == 1
    assert review_results[0]["passed"] is True

    assert persisted.errors == ""
    assert persisted.result == response.result

    updated_task = service.task_repository.get(task.id)
    assert updated_task is not None
    assert updated_task.status == "Completed"
    assert updated_task.result == response.result


def test_run_autonomous_persists_failed_state_and_artifacts(
    db: Session, service: ExecutionService, tmp_path: Path
) -> None:
    """A retry-limited loop persists the failure and never commits."""
    task = _create_task(db)
    repo = make_calculator_repo(tmp_path / "repo")
    worker = ScriptedWorker(repo, [write_broken_calculator])

    response = service.run_autonomous(
        task.id, "ads-worker", worker=worker, repository=repo, max_attempts=2
    )

    assert response.status == "Failed"
    assert response.state == AutonomousState.FAILED.value
    assert response.attempts == 2
    assert response.commit_hash is None
    assert response.verification_status == "Failed"
    assert "tests failed" in (response.errors or "")
    assert "maximum attempts reached" in (response.error_message or "")

    test_results = json.loads(response.test_results or "[]")
    assert len(test_results) == 2
    assert all(run["passed"] is False for run in test_results)

    updated_task = service.task_repository.get(task.id)
    assert updated_task is not None
    assert updated_task.status == "Failed"


def test_restart_keeps_autonomous_execution_state(session_factory, tmp_path: Path) -> None:
    """A fresh process over the same database sees the persisted loop state."""
    session = session_factory()
    task = _create_task(session)
    repo = make_calculator_repo(tmp_path / "repo")
    service = ExecutionService(ExecutionRepository(session), TaskRepository(session))
    response = service.run_autonomous(
        task.id,
        "ads-worker",
        worker=ScriptedWorker(repo, [write_calculator]),
        repository=repo,
    )
    execution_id = response.id
    task_id = task.id
    session.close()

    engine = create_engine(
        f"sqlite:///{tmp_path / 'autonomous.db'}",
        connect_args={"check_same_thread": False},
    )
    Session2 = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session2 = Session2()
    try:
        restarted_execution = session2.get(Execution, execution_id)
        restarted_task = session2.get(Task, task_id)
        assert restarted_execution is not None
        assert restarted_execution.state == "COMPLETED"
        assert restarted_execution.attempts == 1
        assert restarted_execution.commit_hash
        assert restarted_execution.verification_status == "Passed"
        assert restarted_execution.result
        assert restarted_execution.test_results
        assert restarted_execution.review_results
        assert restarted_task is not None
        assert restarted_task.status == "Completed"
    finally:
        session2.close()
        engine.dispose()


def test_run_autonomous_rejects_duplicate_active_execution(
    db: Session, service: ExecutionService, tmp_path: Path
) -> None:
    """A task with an in-flight execution cannot start an autonomous run."""
    task = _create_task(db)
    repo = make_calculator_repo(tmp_path / "repo")

    from app.schemas.execution import ExecutionCreateRequest

    service.repository.create(ExecutionCreateRequest(task_id=task.id, agent_name="worker-a"))

    with pytest.raises(ValueError, match="already has an active execution"):
        service.run_autonomous(
            task.id,
            "worker-b",
            worker=ScriptedWorker(repo, [write_calculator]),
            repository=repo,
        )


def test_run_autonomous_rejects_missing_task(service: ExecutionService) -> None:
    """Executing a nonexistent task fails fast."""
    import uuid

    with pytest.raises(ValueError, match="task not found"):
        service.run_autonomous(uuid.uuid4(), "worker")


def test_run_autonomous_with_native_executor_persists_completed_state(
    db: Session, service: ExecutionService, tmp_path: Path
) -> None:
    """The native GoalOS executor completes and persists its real commit."""
    task = _create_task(db)
    repo = make_calculator_repo(tmp_path / "repo")
    provider = DeterministicEditProvider([calculator_plan()])
    executor = NativeGoalOSCodingExecutor(provider=provider, repository=repo)

    response = service.run_autonomous(
        task.id, "native-executor", executor=executor, repository=repo
    )

    assert response.status == "Completed"
    assert response.state == AutonomousState.COMPLETED.value
    assert response.attempts == 1
    assert response.commit_hash
    assert response.verification_status == "Passed"
    assert "return a + b" in (repo / "calculator.py").read_text()
    assert provider.requests  # the provider was actually consulted

    persisted = service.get(response.id)
    assert persisted is not None
    assert persisted.state == "COMPLETED"
    assert persisted.commit_hash == response.commit_hash

    updated_task = service.task_repository.get(task.id)
    assert updated_task is not None
    assert updated_task.status == "Completed"


def test_run_autonomous_persists_each_state_transition(
    db: Session, service: ExecutionService, tmp_path: Path
) -> None:
    """Intermediate states are persisted as the loop advances, not only at the end."""
    task = _create_task(db)
    repo = make_calculator_repo(tmp_path / "repo")
    worker = ScriptedWorker(repo, [write_broken_calculator, write_calculator])

    response = service.run_autonomous(
        task.id, "ads-worker", worker=worker, repository=repo, max_attempts=3
    )

    assert response.status == "Completed"
    assert response.attempts == 2
    assert response.state == AutonomousState.COMPLETED.value

    # Both test runs are persisted, proving the FIXING cycle is recorded.
    test_results = json.loads(response.test_results or "[]")
    assert [run["passed"] for run in test_results] == [False, True]
    assert "tests failed" in (response.errors or "")
