"""Tests for Autonomous Development System models."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from app.kernel.development.models import DevelopmentTask, TaskStatus, WorkerType


def test_development_task_defaults() -> None:
    """Development tasks receive the expected defaults."""

    task = DevelopmentTask(title="Add ADS model", description="Create task model.")

    assert isinstance(task.id, UUID)
    assert task.files == []
    assert task.worker is WorkerType.CODEX
    assert task.status is TaskStatus.PENDING
    assert task.test_command == "python -m pytest"
    assert task.commit_message == ""
    assert task.dependencies == []


def test_task_status_values() -> None:
    """Task statuses use stable serialized values."""

    assert [status.value for status in TaskStatus] == [
        "pending",
        "running",
        "blocked",
        "failed",
        "completed",
    ]


def test_worker_type_values() -> None:
    """Worker types use stable serialized values."""

    assert [worker.value for worker in WorkerType] == [
        "aider",
        "codex",
        "claude",
        "openhands",
    ]


def test_development_task_generates_unique_ids() -> None:
    """Each task receives a new UUID by default."""

    first_task = DevelopmentTask(title="First", description="First task.")
    second_task = DevelopmentTask(title="Second", description="Second task.")

    assert first_task.id != second_task.id


def test_development_task_supports_files_and_dependencies() -> None:
    """Tasks retain supplied file and dependency lists."""

    dependency = uuid4()
    files = [Path("app/kernel/development/models.py")]
    task = DevelopmentTask(
        title="Extend model",
        description="Add fields.",
        files=files,
        dependencies=[dependency],
    )

    assert task.files == files
    assert task.dependencies == [dependency]


def test_development_task_accepts_custom_fields() -> None:
    """Tasks accept custom field values."""

    task_id = uuid4()
    task = DevelopmentTask(
        title="Custom task",
        description="Use non-default values.",
        id=task_id,
        worker=WorkerType.CLAUDE,
        status=TaskStatus.RUNNING,
        test_command="python -m pytest tests/kernel",
        commit_message="Add custom ADS task",
    )

    assert task.id == task_id
    assert task.worker is WorkerType.CLAUDE
    assert task.status is TaskStatus.RUNNING
    assert task.test_command == "python -m pytest tests/kernel"
    assert task.commit_message == "Add custom ADS task"
