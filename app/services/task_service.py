"""
Task business service.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from app.agents.permissions import Permission
from app.db.models.task import Task
from app.repositories.task_repository import TaskRepository
from app.schemas.task import (
    TaskCreateRequest,
    TaskResponse,
    TaskSummaryResponse,
    TaskUpdateRequest,
)
from app.services.integration_service import IntegrationService


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

    # ------------------------------------------------------------------
    # Integration execution
    # ------------------------------------------------------------------
    def execute_integration(
        self,
        task_id: uuid.UUID,
        params: dict[str, Any] | None,
        permissions: set[Permission] | list[Permission] | None,
        integration_service: IntegrationService,
        capability: str | None = None,
    ) -> dict[str, Any] | None:
        """Execute the integration a task requires, persisting the result.

        The task identifies its integration through
        ``required_integration``/``required_capability`` (requirement: a
        task must be able to declare which integration/capability it
        needs). The integration runs through the existing connector, the
        run is persisted as a runtime execution record, and the task's
        status/result are updated from the structured outcome.

        Returns ``None`` when the task does not exist; raises
        ``ValueError`` when the task does not declare an integration.
        """
        task = self.repository.get(task_id)
        if task is None:
            return None
        integration_name = task.required_integration
        capability_name = capability or task.required_capability
        if not integration_name or not capability_name:
            raise ValueError(
                "task does not declare a required integration/capability "
                "(set required_integration and required_capability)"
            )
        response = integration_service.execute(
            integration_name,
            capability_name,
            params,
            permissions,
        )
        status = "Completed" if response.status == "OK" else "Failed"
        result_text = (
            json.dumps(response.result)
            if response.result is not None
            else (response.error or "")
        )
        self.repository.update(
            task,
            {"status": status, "result": result_text or None},
        )
        return {
            "task": self._to_response(task),
            "execution": response,
        }
