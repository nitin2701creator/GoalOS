"""Tests for ADS scheduling: eligibility, ordering, and dependencies."""

from __future__ import annotations

from uuid import uuid4

from app.kernel.development.models import DevelopmentTask, TaskStatus
from app.kernel.development.scheduler import DevelopmentScheduler


def make_task(
    title: str,
    *,
    status: TaskStatus = TaskStatus.PENDING,
    dependencies: list | None = None,
) -> DevelopmentTask:
    """Create a development task for scheduler tests."""
    return DevelopmentTask(
        title=title,
        description=f"{title} description.",
        status=status,
        dependencies=dependencies or [],
    )


def test_no_tasks_returns_none() -> None:
    """An empty task set schedules nothing."""

    assert DevelopmentScheduler().select_next(()) is None


def test_returns_first_pending_task() -> None:
    """The earliest pending task is selected first."""

    first = make_task("First")
    second = make_task("Second")

    assert DevelopmentScheduler().select_next((first, second)) is first


def test_skips_non_pending_tasks() -> None:
    """Running and completed tasks are not eligible for selection."""

    completed = make_task("Completed", status=TaskStatus.COMPLETED)
    running = make_task("Running", status=TaskStatus.RUNNING)
    pending = make_task("Pending")

    assert DevelopmentScheduler().select_next((completed, running, pending)) is pending


def test_task_with_pending_dependency_is_blocked() -> None:
    """A task cannot run before its dependency completes."""

    dependency = make_task("Dependency")
    dependent = make_task("Dependent", dependencies=[dependency.id])

    scheduler = DevelopmentScheduler()

    assert scheduler.select_next((dependency, dependent)) is dependency
    assert scheduler.select_next((dependent,)) is None


def test_task_becomes_eligible_after_dependency_completes() -> None:
    """Completing a dependency unlocks the dependent task."""

    dependency = make_task("Dependency")
    dependent = make_task("Dependent", dependencies=[dependency.id])
    scheduler = DevelopmentScheduler()

    dependency.status = TaskStatus.COMPLETED

    assert scheduler.select_next((dependency, dependent)) is dependent


def test_unknown_dependency_blocks_task() -> None:
    """A dependency that is not a known task keeps the task ineligible."""

    task = make_task("Orphan", dependencies=[uuid4()])

    assert DevelopmentScheduler().select_next((task,)) is None


def test_failed_dependency_blocks_task() -> None:
    """Only completed dependencies unlock a task."""

    failed = make_task("Failed", status=TaskStatus.FAILED)
    dependent = make_task("Dependent", dependencies=[failed.id])

    assert DevelopmentScheduler().select_next((failed, dependent)) is None


def test_selection_is_deterministic() -> None:
    """Repeated selection over the same state returns the same task."""

    tasks = (
        make_task("A"),
        make_task("B"),
        make_task("C"),
    )
    scheduler = DevelopmentScheduler()

    assert scheduler.select_next(tasks) is scheduler.select_next(tasks)
