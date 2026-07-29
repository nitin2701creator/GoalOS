"""Tests for Autonomous Development System backlog management."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.kernel.development.backlog import Backlog
from app.kernel.development.models import DevelopmentTask, TaskStatus


def make_task(title: str, status: TaskStatus = TaskStatus.PENDING) -> DevelopmentTask:
    """Create a task for backlog tests."""

    return DevelopmentTask(title=title, description=f"{title} description.", status=status)


def test_empty_backlog() -> None:
    """An empty backlog has no tasks or next task."""

    backlog = Backlog()

    assert backlog.list() == []
    assert backlog.pending() == []
    assert backlog.completed() == []
    assert backlog.next_task() is None


def test_add_and_get_task() -> None:
    """Added tasks can be retrieved by identifier."""

    backlog = Backlog()
    task = make_task("Add model")

    backlog.add(task)

    assert backlog.get(task.id) is task


def test_remove_task() -> None:
    """Removing a task returns it and removes it from the backlog."""

    backlog = Backlog()
    task = make_task("Remove model")
    backlog.add(task)

    assert backlog.remove(task.id) is task
    assert backlog.get(task.id) is None


def test_list_tasks_preserves_addition_order() -> None:
    """Listing tasks returns every task in insertion order."""

    backlog = Backlog()
    first_task = make_task("First")
    second_task = make_task("Second")
    backlog.add(first_task)
    backlog.add(second_task)

    assert backlog.list() == [first_task, second_task]


def test_pending_and_completed_tasks() -> None:
    """Status filters return their corresponding tasks."""

    backlog = Backlog()
    pending_task = make_task("Pending")
    completed_task = make_task("Completed", TaskStatus.COMPLETED)
    running_task = make_task("Running", TaskStatus.RUNNING)
    for task in (pending_task, completed_task, running_task):
        backlog.add(task)

    assert backlog.pending() == [pending_task]
    assert backlog.completed() == [completed_task]


def test_next_task_returns_first_pending_task() -> None:
    """The next task is the first pending task by insertion order."""

    backlog = Backlog()
    completed_task = make_task("Completed", TaskStatus.COMPLETED)
    first_pending_task = make_task("First pending")
    second_pending_task = make_task("Second pending")
    for task in (completed_task, first_pending_task, second_pending_task):
        backlog.add(task)

    assert backlog.next_task() is first_pending_task


def test_add_rejects_duplicate_task_ids() -> None:
    """The backlog rejects duplicate task identifiers."""

    backlog = Backlog()
    task = make_task("Original")
    duplicate = DevelopmentTask(
        title="Duplicate",
        description="Duplicate identifier.",
        id=task.id,
    )
    backlog.add(task)

    with pytest.raises(ValueError, match="Task already exists"):
        backlog.add(duplicate)


def test_missing_task_ids_return_none_or_raise_key_error() -> None:
    """Missing task identifiers have explicit lookup and removal behavior."""

    backlog = Backlog()
    missing_id = uuid4()

    assert backlog.get(missing_id) is None
    with pytest.raises(KeyError):
        backlog.remove(missing_id)
