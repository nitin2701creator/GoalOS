"""Tests for ADS deterministic planning behavior."""

from __future__ import annotations

import pytest

from app.kernel.development.models import TaskStatus, WorkerType
from app.kernel.development.planner import DevelopmentPlanner


def test_plan_produces_dependency_ordered_tasks() -> None:
    """A plan covers the full lifecycle with chained dependencies."""

    tasks = DevelopmentPlanner().plan("Add analytics module")

    titles = [task.title for task in tasks]
    assert titles == [
        "Define requirements for Add analytics module",
        "Implement Add analytics module",
        "Test Add analytics module",
        "Document and finalize Add analytics module",
    ]
    assert tasks[0].dependencies == []
    for index in range(1, len(tasks)):
        assert tasks[index].dependencies == [tasks[index - 1].id]


def test_plan_is_deterministic() -> None:
    """The same objective always produces the same plan."""

    planner = DevelopmentPlanner()

    first = planner.plan("Reduce costs")
    second = planner.plan("Reduce costs")

    assert [task.title for task in first] == [task.title for task in second]
    assert [task.id for task in first] != [task.id for task in second]


def test_plan_tasks_start_pending_with_default_worker() -> None:
    """Planned tasks are pending and use the default worker type."""

    tasks = DevelopmentPlanner().plan("Ship onboarding")

    assert all(task.status is TaskStatus.PENDING for task in tasks)
    assert all(task.worker is WorkerType.CODEX for task in tasks)


def test_plan_requires_non_empty_objective() -> None:
    """A blank objective is rejected."""

    with pytest.raises(ValueError, match="must not be empty"):
        DevelopmentPlanner().plan("   ")
