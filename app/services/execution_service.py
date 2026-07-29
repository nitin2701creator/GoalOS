"""
Execution business service.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.db.models.execution import Execution, ExecutionStatus
from app.repositories.execution_repository import ExecutionRepository
from app.schemas.execution import (
    ExecutionCreateRequest,
    ExecutionResponse,
    ExecutionSummaryResponse,
    ExecutionUpdateRequest,
)


class ExecutionService:
    """Business operations for task executions."""

    def __init__(self, repository: ExecutionRepository):
        self.repository = repository

    def _to_response(self, execution: Execution) -> ExecutionResponse:
        return ExecutionResponse.model_validate(execution)

    def create_execution(self, request: ExecutionCreateRequest) -> ExecutionResponse:
        data = request.model_dump(exclude_unset=True)
        if data.get("status") is None:
            data["status"] = ExecutionStatus.PENDING
        execution = self.repository.create(ExecutionCreateRequest.model_validate(data))
        return self._to_response(execution)

    def get(self, execution_id: str) -> ExecutionResponse | None:
        execution = self.repository.get(execution_id)
        if execution is None:
            return None
        return self._to_response(execution)

    def list_executions(self) -> list[ExecutionResponse]:
        return [self._to_response(execution) for execution in self.repository.list()]

    def list_task_executions(self, task_id: UUID) -> list[ExecutionResponse]:
        return [self._to_response(execution) for execution in self.repository.list_by_task(task_id)]

    def latest_execution(self, task_id: UUID) -> ExecutionResponse | None:
        execution = self.repository.latest_execution(task_id)
        if execution is None:
            return None
        return self._to_response(execution)

    def update_execution(self, execution_id: UUID, request: ExecutionUpdateRequest) -> ExecutionResponse | None:
        execution = self.repository.get(execution_id)
        if execution is None:
            return None

        updates = request.model_dump(exclude_unset=True)
        if not updates:
            return self._to_response(execution)

        return self._to_response(self.repository.update(execution, updates))

    def delete_execution(self, execution_id: UUID) -> bool:
        execution = self.repository.get(execution_id)
        if execution is None:
            return False

        self.repository.delete(execution)
        return True

    def assign_agent(self, execution_id: UUID, agent_name: str) -> ExecutionResponse | None:
        execution = self.repository.get(execution_id)
        if execution is None:
            return None

        execution.agent_name = agent_name
        return self._to_response(self.repository.update(execution, {"agent_name": agent_name}))

    def append_execution_log(self, execution_id: UUID, log_message: str) -> ExecutionResponse | None:
        execution = self.repository.get(execution_id)
        if execution is None:
            return None

        execution.execution_logs = (
            (execution.execution_logs or "") + log_message
        )
        return self._to_response(self.repository.update(execution, {"execution_logs": execution.execution_logs}))

    def update_execution_status(self, execution_id: UUID, status: ExecutionStatus) -> ExecutionResponse | None:
        execution = self.repository.get(execution_id)
        if execution is None:
            return None

        execution.status = status
        return self._to_response(self.repository.update(execution, {"status": status}))

    def store_result(self, execution_id: UUID, result: str) -> ExecutionResponse | None:
        execution = self.repository.get(execution_id)
        if execution is None:
            return None

        execution.result = result
        return self._to_response(self.repository.update(execution, {"result": result}))

    def store_error(self, execution_id: UUID, error_message: str) -> ExecutionResponse | None:
        execution = self.repository.get(execution_id)
        if execution is None:
            return None

        execution.error_message = error_message
        return self._to_response(self.repository.update(execution, {"error_message": error_message}))

    def start_execution(self, execution_id: UUID) -> ExecutionResponse | None:
        execution = self.repository.get(execution_id)
        if execution is None:
            return None

        execution.status = ExecutionStatus.RUNNING
        execution.started_at = datetime.now(timezone.utc)
        return self._to_response(self.repository.update(execution, {
            "status": execution.status,
            "started_at": execution.started_at,
        }))

    def complete_execution(self, execution_id: UUID, result: str | None = None) -> ExecutionResponse | None:
        execution = self.repository.get(execution_id)
        if execution is None:
            return None

        execution.status = ExecutionStatus.COMPLETED
        execution.completed_at = datetime.now(timezone.utc)
        execution.execution_duration_seconds = int(
            (execution.completed_at - execution.started_at).total_seconds()
        ) if execution.started_at else None
        execution.result = result

        return self._to_response(self.repository.update(execution, {
            "status": execution.status,
            "completed_at": execution.completed_at,
            "execution_duration_seconds": execution.execution_duration_seconds,
            "result": execution.result,
        }))

    def fail_execution(self, execution_id: UUID, error_message: str) -> ExecutionResponse | None:
        execution = self.repository.get(execution_id)
        if execution is None:
            return None

        execution.status = ExecutionStatus.FAILED
        execution.completed_at = datetime.now(timezone.utc)
        execution.error_message = error_message
        execution.execution_duration_seconds = int(
            (execution.completed_at - execution.started_at).total_seconds()
        ) if execution.started_at else None

        return self._to_response(self.repository.update(execution, {
            "status": execution.status,
            "completed_at": execution.completed_at,
            "error_message": execution.error_message,
            "execution_duration_seconds": execution.execution_duration_seconds,
        }))

    def retry_execution(self, execution_id: UUID) -> ExecutionResponse | None:
        execution = self.repository.get(execution_id)
        if execution is None:
            return None

        execution.retry_count += 1
        execution.status = ExecutionStatus.RETRYING

        return self._to_response(self.repository.update(execution, {
            "retry_count": execution.retry_count,
            "status": execution.status,
        }))

    def cancel_execution(self, execution_id: UUID) -> ExecutionResponse | None:
        execution = self.repository.get(execution_id)
        if execution is None:
            return None

        execution.status = ExecutionStatus.CANCELLED

        return self._to_response(self.repository.update(execution, {
            "status": execution.status,
        }))

    def execution_summary(self, task_id: str) -> ExecutionSummaryResponse:
        executions = self.repository.list_by_task(task_id)
        total = len(executions)
        completed = sum(1 for exec_ in executions if exec_.status == ExecutionStatus.COMPLETED)
        failed = sum(1 for exec_ in executions if exec_.status == ExecutionStatus.FAILED)
        running = sum(1 for exec_ in executions if exec_.status == ExecutionStatus.RUNNING)
        pending = sum(1 for exec_ in executions if exec_.status == ExecutionStatus.PENDING)
        cancelled = sum(1 for exec_ in executions if exec_.status == ExecutionStatus.CANCELLED)
        retrying = sum(1 for exec_ in executions if exec_.status == ExecutionStatus.RETRYING)
        last_execution = self.repository.latest_execution(task_id)

        return ExecutionSummaryResponse(
            total_executions=total,
            completed=completed,
            failed=failed,
            running=running,
            pending=pending,
            cancelled=cancelled,
            retrying=retrying,
            last_execution=self._to_response(last_execution) if last_execution is not None else None,
        )
