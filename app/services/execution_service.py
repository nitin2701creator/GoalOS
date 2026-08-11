"""
Execution business service.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from app.db.models.execution import Execution, ExecutionStatus
from app.db.models.task import Task
from app.kernel.development.autonomous import (
    AutonomousLoop,
    AutonomousRunRecord,
    AutonomousState,
)
from app.kernel.development.executors import CodingExecutor
from app.kernel.development.git_manager import GitManager
from app.kernel.development.models import DevelopmentTask, WorkerType
from app.kernel.development.prompt_builder import PromptBuilder
from app.kernel.development.verifier import DevelopmentVerifier, VerificationResult
from app.kernel.development.worker import (
    DevelopmentWorker,
    MockWorker,
    WorkerResult,
    WorkerUnavailableError,
    create_worker,
)
from app.repositories.execution_repository import ExecutionRepository
from app.repositories.task_repository import TaskRepository
from app.schemas.execution import (
    ExecutionCreateRequest,
    ExecutionResponse,
    ExecutionSummaryResponse,
    ExecutionUpdateRequest,
)


class ExecutionService:
    """Business operations for task executions.

    The service covers the classic CRUD operations as well as the
    end-to-end ``run_task`` lifecycle used by the API: a task is
    submitted, claimed atomically by a worker, executed against the
    repository, verified, and every result — including failure and
    verification state — is persisted so a restart never loses it.
    """

    def __init__(
        self,
        repository: ExecutionRepository,
        task_repository: TaskRepository | None = None,
    ) -> None:
        self.repository = repository
        self.task_repository = task_repository

    def _to_response(self, execution: Execution) -> ExecutionResponse:
        return ExecutionResponse.model_validate(execution)

    @staticmethod
    def _duration_seconds(started_at: datetime | None, completed_at: datetime) -> int | None:
        """Compute a safe duration between a started and completed stamp.

        SQLite returns naive datetimes even for timezone-aware columns, so
        both stamps are normalized to UTC before subtraction.
        """
        if started_at is None:
            return None
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        return int((completed_at - started_at).total_seconds())

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
        execution.execution_duration_seconds = self._duration_seconds(
            execution.started_at, execution.completed_at
        )
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
        execution.execution_duration_seconds = self._duration_seconds(
            execution.started_at, execution.completed_at
        )

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

    # ------------------------------------------------------------------ #
    # End-to-end task execution
    # ------------------------------------------------------------------ #
    def run_autonomous(
        self,
        task_id: UUID,
        agent_name: str,
        worker_type: str | None = None,
        worker: DevelopmentWorker | None = None,
        verifier: DevelopmentVerifier | None = None,
        executor: CodingExecutor | None = None,
        repository: Path | None = None,
        max_attempts: int = 3,
    ) -> ExecutionResponse:
        """Run a task through the autonomous development loop, fully persisted.

        The loop drives the task from repository inspection through
        implementation, test runs, bounded repair, review, and a
        verification-gated commit. Every state transition and artifact is
        persisted on the execution record as the loop runs, so a restart
        never loses execution state:

        - ``state``: the autonomous state machine (PLANNING, IMPLEMENTING,
          TESTING, FIXING, REVIEWING, COMMITTING, COMPLETED, FAILED);
        - ``attempts``: bounded implementation runs performed;
        - ``test_results`` / ``errors`` / ``review_results``: accumulated
          artifacts in execution order;
        - ``result``: final worker output; ``commit_hash``: the
          verification-gated commit.

        Args:
            task_id: The task to execute.
            agent_name: Identity of the worker claiming the task.
            worker_type: ``mock`` (default) or a coding CLI name
                (``codex``, ``aider``, ``claude``, ``openhands``).
            worker: Optional explicit worker overriding ``worker_type``.
            verifier: Optional verification strategy (kernel default).
            executor: Optional coding executor (e.g. the native GoalOS
                executor or the Aider adapter); when provided it takes
                precedence over the worker.
            repository: Repository root inspected, tested, and committed.
            max_attempts: Hard bound on autonomous implementation runs.

        Returns:
            The persisted execution with its final state.

        Raises:
            ValueError: If the task does not exist or an execution is
                already in flight.
        """
        if self.task_repository is None:
            raise ValueError("task repository is required for autonomous execution")

        task = self.task_repository.get(task_id)
        if task is None:
            raise ValueError(f"task not found: {task_id}")

        if self.repository.active_execution(task_id) is not None:
            raise ValueError(f"task already has an active execution: {task_id}")

        execution = self.repository.create(
            ExecutionCreateRequest(task_id=task_id, agent_name=agent_name)
        )
        claimed = self.repository.claim(execution.id)
        if claimed is None:
            raise ValueError("execution could not be claimed; it was already claimed or completed")
        execution = claimed
        self.task_repository.update(task, {"status": "Running"})

        repository_root = repository or Path.cwd()
        loop = AutonomousLoop(
            worker=self._resolve_worker(worker_type, worker, repository_root),
            verifier=verifier,
            executor=executor,
            git_manager=GitManager(repository_root),
            repository=repository_root,
            max_attempts=max_attempts,
            on_state=lambda state, record: self.repository.update(
                execution, self._loop_updates(record, state)
            ),
        )
        record = loop.run(task.description or task.title)

        final_result = record.final_result
        final_output = final_result.output if final_result is not None else None
        verification_passed = (
            record.final_verification is not None and record.final_verification.passed
        )
        self.repository.update(
            execution,
            {
                **self._loop_updates(record, record.state),
                "result": final_output,
                "verification_status": "Passed" if verification_passed else "Failed",
                "verification_summary": (
                    record.final_verification.summary
                    if record.final_verification is not None
                    else None
                ),
                "commit_hash": record.commit_hash,
            },
        )

        if record.state is AutonomousState.COMPLETED:
            finalized = self.complete_execution(execution.id, final_output)
            self.task_repository.update(task, {"status": "Completed", "result": final_output})
        else:
            error_message = "; ".join(record.errors) if record.errors else record.state.value
            finalized = self.fail_execution(execution.id, error_message)
            self.task_repository.update(task, {"status": "Failed", "result": final_output})

        if finalized is None:  # pragma: no cover - defensive; execution always exists here
            raise RuntimeError(f"execution {execution.id} could not be finalized")
        return self._to_response(finalized)

    @staticmethod
    def _loop_updates(
        record: AutonomousRunRecord,
        state: AutonomousState,
    ) -> dict[str, Any]:
        """Serialize one record snapshot into persisted execution fields."""
        return {
            "state": state.value,
            "attempts": record.attempts,
            "test_results": json.dumps(
                [
                    {
                        "command": run.command,
                        "passed": run.passed,
                        "exit_code": run.exit_code,
                        "output": run.output,
                    }
                    for run in record.test_runs
                ]
            ),
            "errors": "\n".join(record.errors),
            "review_results": json.dumps(
                [
                    {
                        "passed": review.passed,
                        "findings": list(review.findings),
                        "summary": review.summary,
                    }
                    for review in record.review_results
                ]
            ),
        }

    def run_task(
        self,
        task_id: UUID,
        agent_name: str,
        worker_type: str | None = None,
        worker: DevelopmentWorker | None = None,
        verifier: DevelopmentVerifier | None = None,
        repository: Path | None = None,
    ) -> ExecutionResponse:
        """Submit, claim, execute, verify, and persist a task end to end.

        The lifecycle is fully persisted so a process restart can resume
        from the stored state:

        1. the task must exist (``ValueError`` otherwise);
        2. an in-flight execution for the task prevents a duplicate
           submission (``ValueError`` otherwise);
        3. an execution record is created (``Pending``), then claimed
           atomically (``Pending`` → ``Running``);
        4. the worker runs the built prompt; the result is verified;
        5. result, verification verdict, and final execution/task status
           are persisted.

        Args:
            task_id: The task to execute.
            agent_name: Identity of the worker claiming the task.
            worker_type: ``mock`` (default) or a coding CLI name
                (``codex``, ``aider``, ``claude``, ``openhands``).
            worker: Optional explicit worker overriding ``worker_type``.
            verifier: Optional verification strategy (kernel default).
            repository: Repository root used by CLI workers.

        Returns:
            The persisted execution with its final state.

        Raises:
            ValueError: If the task does not exist, an execution is already
                in flight, or ``worker_type`` is unsupported.
        """
        if self.task_repository is None:
            raise ValueError("task repository is required for task execution")

        task = self.task_repository.get(task_id)
        if task is None:
            raise ValueError(f"task not found: {task_id}")

        if self.repository.active_execution(task_id) is not None:
            raise ValueError(f"task already has an active execution: {task_id}")

        execution = self.repository.create(
            ExecutionCreateRequest(task_id=task_id, agent_name=agent_name)
        )
        claimed = self.repository.claim(execution.id)
        if claimed is None:
            raise ValueError("execution could not be claimed; it was already claimed or completed")
        execution = claimed
        self.task_repository.update(task, {"status": "Running"})

        result, verification = self._execute(task, worker_type, worker, verifier, repository)

        self.repository.update(execution, {
            "result": result.output,
            "verification_status": "Passed" if verification.passed else "Failed",
            "verification_summary": verification.summary,
        })

        if result.success and verification.passed:
            finalized = self.complete_execution(execution.id, result.output)
            self.task_repository.update(task, {"status": "Completed", "result": result.output})
        else:
            error_message = result.summary if not result.success else verification.summary
            finalized = self.fail_execution(execution.id, error_message)
            self.task_repository.update(task, {"status": "Failed", "result": result.output})

        if finalized is None:  # pragma: no cover - defensive; execution always exists here
            raise RuntimeError(f"execution {execution.id} could not be finalized")
        return self._to_response(finalized)

    def _execute(
        self,
        task: Task,
        worker_type: str | None,
        worker: DevelopmentWorker | None,
        verifier: DevelopmentVerifier | None,
        repository: Path | None,
    ) -> tuple[WorkerResult, VerificationResult]:
        """Run the worker and verify its result, tolerating runtime failures."""
        resolved_worker = self._resolve_worker(worker_type, worker, repository)
        kernel_task = DevelopmentTask(
            title=task.title,
            description=task.description,
            worker=WorkerType.CODEX,
        )
        prompt = PromptBuilder().build(kernel_task)
        try:
            result = resolved_worker.execute(prompt)
        except WorkerUnavailableError as exc:
            result = WorkerResult(success=False, summary=str(exc), output=str(exc))
        except Exception as exc:  # noqa: BLE001 - a crashing worker must persist a failure
            result = WorkerResult(
                success=False,
                summary=f"worker crashed: {exc}",
                output=str(exc),
            )
        verification = (verifier or DevelopmentVerifier()).verify(kernel_task, result)
        return result, verification

    @staticmethod
    def _resolve_worker(
        worker_type: str | None,
        worker: DevelopmentWorker | None,
        repository: Path | None,
    ) -> DevelopmentWorker:
        """Resolve the worker for a run, defaulting to the mock worker."""
        if worker is not None:
            return worker
        if worker_type is None or worker_type.strip().lower() == "mock":
            return MockWorker()
        try:
            resolved_type = WorkerType(worker_type.strip().lower())
        except ValueError as exc:
            raise ValueError(f"unsupported worker type: {worker_type}") from exc
        return create_worker(resolved_type, repository=repository)
