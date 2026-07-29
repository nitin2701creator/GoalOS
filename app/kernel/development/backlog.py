"""In-memory backlog management for Autonomous Development System tasks."""

from __future__ import annotations

from uuid import UUID

from app.kernel.development.models import DevelopmentTask, TaskStatus


class Backlog:
    """Manage an ordered collection of development tasks in memory."""

    def __init__(self) -> None:
        """Initialize an empty backlog."""

        self._tasks: dict[UUID, DevelopmentTask] = {}

    def add(self, task: DevelopmentTask) -> None:
        """Add a task, rejecting an existing task identifier."""

        if task.id in self._tasks:
            raise ValueError(f"Task already exists: {task.id}")
        self._tasks[task.id] = task

    def remove(self, task_id: UUID) -> DevelopmentTask:
        """Remove and return the task identified by ``task_id``."""

        return self._tasks.pop(task_id)

    def get(self, task_id: UUID) -> DevelopmentTask | None:
        """Return the task identified by ``task_id``, if present."""

        return self._tasks.get(task_id)

    def list(self) -> list[DevelopmentTask]:
        """Return all tasks in insertion order."""

        return list(self._tasks.values())

    def pending(self) -> list[DevelopmentTask]:
        """Return tasks whose status is pending."""

        return self._with_status(TaskStatus.PENDING)

    def completed(self) -> list[DevelopmentTask]:
        """Return tasks whose status is completed."""

        return self._with_status(TaskStatus.COMPLETED)

    def next_task(self) -> DevelopmentTask | None:
        """Return the first pending task, if one exists."""

        return next(iter(self.pending()), None)

    def _with_status(self, status: TaskStatus) -> list[DevelopmentTask]:
        """Return tasks matching a lifecycle status."""

        return [task for task in self._tasks.values() if task.status is status]
