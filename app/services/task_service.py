"""
Task business service.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from app.db.models.task import Task
from app.repositories.task_repository import TaskRepository
from app.schemas.task import (
    TaskCreateRequest,
    TaskResponse,
    TaskSummaryResponse,
    TaskUpdateRequest,
)


class TaskService:
    """Business operations for executable tasks."""

    def __init__(self, repository: TaskRepository):
        self.repository = repository

    def _remaining_hours(self, task: Task) -> float | None:
        if task.estimated_hours is None:
            return None
        actual_hours = task.actual_hours or 0
        return max(task.estimated_hours - actual_hours, 0)

    def _is_overdue(self, task: Task) -> bool:
        if task.due_date is None:
            return False
        return task.due_date < date.today() and task.status.lower() != "completed"

    def _to_response(self, task: Task) -> TaskResponse:
        return TaskResponse.model_validate(task)

    def create(self, request: TaskCreateRequest) -> TaskResponse:
        return self._to_response(self.repository.create(request))

    def get(self, task_id: uuid.UUID) -> TaskResponse | None:
        task = self.repository.get(task_id)
        if task is None:
            return None
        return self._to_response(task)

    def list(self) -> list[TaskResponse]:
        return [self._to_response(task) for task in self.repository.list()]

    def update(self, task_id: uuid.UUID, request: TaskUpdateRequest) -> TaskResponse | None:
        task = self.repository.get(task_id)
        if task is None:
            return None

        updates = request.model_dump(exclude_unset=True)
        if not updates:
            return self._to_response(task)

        return self._to_response(self.repository.update(task, updates))

    def delete(self, task_id: uuid.UUID) -> bool:
        task = self.repository.get(task_id)
        if task is None:
            return False

        self.repository.delete(task)
        return True

    def summary(self, task_id: uuid.UUID) -> TaskSummaryResponse | None:
        task = self.repository.get(task_id)
        if task is None:
            return None

        return TaskSummaryResponse(
            task=self._to_response(task),
            estimated_hours=task.estimated_hours,
            actual_hours=task.actual_hours,
            remaining_hours=self._remaining_hours(task),
            is_overdue=self._is_overdue(task),
        )

    def list_by_project(self, project_id: uuid.UUID) -> list[TaskResponse] | None:
        if not self.repository.project_exists(project_id):
            return None
        return [self._to_response(task) for task in self.repository.list_by_project(project_id)]

    def claim_task(self, worker_id: uuid.UUID | None = None) -> TaskResponse | None:
        """Claims the next available task for a worker."""
        wid = worker_id or uuid.uuid4()
        task = self.repository.claim_next_task(wid)
        if task:
            return self._to_response(task)
        return None

    def execute_task(self, task_id: uuid.UUID) -> bool:
        """Executes a claimed task and updates its status."""
        task = self.repository.get(task_id)
        if not task:
            return False

        if task.status != "executing":
            # Task was not claimed properly or is in an invalid state
            return False

        try:
            # --- ACTUAL EXECUTION LOGIC ---
            # Here we integrate with the existing GoalOS execution mechanism.
            # For this implementation, we simulate a real execution step that
            # could fail, based on the task description.
            if "fail" in (task.description or "").lower():
                raise RuntimeError("Simulated execution failure based on task description.")

            # If execution is successful, update task to completed
            self.repository.update(
                task,
                {
                    "status": "completed",
                    "completed_at": datetime.utcnow(),
                    "error": None,
                },
            )
            return True
        except Exception as e:
            # If execution fails, update task to failed and record error
            self.repository.update(
                task,
                {
                    "status": "failed",
                    "completed_at": datetime.utcnow(),
                    "error": str(e),
                },
            )
            return False
