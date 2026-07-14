"""
Workflow business service.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.db.models.execution import ExecutionStatus
from app.db.models.workflow import Workflow, WorkflowStatus
from app.repositories.workflow_repository import WorkflowRepository
from app.repositories.execution_repository import ExecutionRepository
from app.schemas.workflow import WorkflowCreateRequest, WorkflowResponse, WorkflowUpdateRequest


class WorkflowService:
    """Business operations for workflow orchestration."""

    def __init__(self, repository: WorkflowRepository, execution_repository: ExecutionRepository):
        self.repository = repository
        self.execution_repository = execution_repository

    def _to_response(self, workflow: Workflow) -> WorkflowResponse:
        return WorkflowResponse.model_validate(workflow)

    def create(self, request: WorkflowCreateRequest) -> WorkflowResponse:
        data = request.model_dump(exclude_unset=True)
        if data.get("status") is None:
            data["status"] = WorkflowStatus.PENDING
        if data.get("progress_percentage") is None:
            data["progress_percentage"] = 0
        workflow = self.repository.create(WorkflowCreateRequest.model_validate(data))
        return self._to_response(workflow)

    def get(self, workflow_id: UUID) -> WorkflowResponse | None:
        workflow = self.repository.get_with_tasks(workflow_id)
        if workflow is None:
            return None
        return self._to_response(workflow)

    def list(self) -> list[WorkflowResponse]:
        return [self._to_response(workflow) for workflow in self.repository.list()]

    def list_by_project(self, project_id: UUID) -> list[WorkflowResponse] | None:
        if not self.repository.project_exists(project_id):
            return None
        return [self._to_response(workflow) for workflow in self.repository.list_by_project(project_id)]

    def update(self, workflow_id: UUID, request: WorkflowUpdateRequest) -> WorkflowResponse | None:
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None
        updates = request.model_dump(exclude_unset=True)
        if not updates:
            return self._to_response(workflow)
        return self._to_response(self.repository.update(workflow, updates))

    def delete(self, workflow_id: UUID) -> bool:
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return False
        self.repository.delete(workflow)
        return True

    def start(self, workflow_id: UUID) -> WorkflowResponse | None:
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None

        workflow.status = WorkflowStatus.RUNNING
        workflow.started_at = datetime.now(timezone.utc)
        if workflow.progress_percentage is None:
            workflow.progress_percentage = 0

        return self._to_response(self.repository.update(workflow, {
            "status": workflow.status,
            "started_at": workflow.started_at,
            "progress_percentage": workflow.progress_percentage,
        }))

    def complete(self, workflow_id: UUID) -> WorkflowResponse | None:
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None

        workflow.status = WorkflowStatus.COMPLETED
        workflow.completed_at = datetime.now(timezone.utc)
        workflow.progress_percentage = 100

        return self._to_response(self.repository.update(workflow, {
            "status": workflow.status,
            "completed_at": workflow.completed_at,
            "progress_percentage": workflow.progress_percentage,
        }))

    def fail(self, workflow_id: UUID, error_message: str | None = None) -> WorkflowResponse | None:
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None

        workflow.status = WorkflowStatus.FAILED
        workflow.completed_at = datetime.now(timezone.utc)

        return self._to_response(self.repository.update(workflow, {
            "status": workflow.status,
            "completed_at": workflow.completed_at,
        }))

    def progress(self, workflow_id: UUID, progress_percentage: int) -> WorkflowResponse | None:
        workflow = self.repository.get(workflow_id)
        if workflow is None:
            return None

        workflow.progress_percentage = max(0, min(progress_percentage, 100))
        return self._to_response(self.repository.update(workflow, {"progress_percentage": workflow.progress_percentage}))

    def update_status_from_tasks(self, workflow_id: UUID) -> WorkflowResponse | None:
        workflow = self.repository.get_with_tasks(workflow_id)
        if workflow is None:
            return None

        tasks = workflow.tasks
        if not tasks:
            workflow.status = WorkflowStatus.PENDING
            workflow.progress_percentage = 0
        else:
            completed_tasks = [task for task in tasks if task.status.lower() == "completed"]
            workflow.progress_percentage = int((len(completed_tasks) / len(tasks)) * 100)
            if all(task.status.lower() == "completed" for task in tasks):
                workflow.status = WorkflowStatus.COMPLETED
                workflow.completed_at = datetime.now(timezone.utc)
            elif any(task.status.lower() == "failed" for task in tasks):
                workflow.status = WorkflowStatus.FAILED
            elif any(task.status.lower() == "running" for task in tasks):
                workflow.status = WorkflowStatus.RUNNING
            else:
                workflow.status = WorkflowStatus.PENDING

        return self._to_response(self.repository.update(workflow, {
            "status": workflow.status,
            "progress_percentage": workflow.progress_percentage,
            "completed_at": workflow.completed_at,
        }))
