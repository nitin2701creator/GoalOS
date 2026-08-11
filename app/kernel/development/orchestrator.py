"""Orchestration boundary for the Autonomous Development System."""

from __future__ import annotations

from dataclasses import dataclass

from app.kernel.development.models import DevelopmentTask, TaskStatus, WorkerType
from app.kernel.development.planner import DevelopmentPlanner
from app.kernel.development.prompt_builder import PromptBuilder
from app.kernel.development.reviewer import DevelopmentReviewer
from app.kernel.development.scheduler import DevelopmentScheduler
from app.kernel.development.verifier import DevelopmentVerifier, VerificationResult
from app.kernel.development.worker import (
    DevelopmentWorker,
    MockWorker,
    WorkerRegistry,
    WorkerResult,
    WorkerUnavailableError,
)


@dataclass(frozen=True, slots=True)
class TaskExecutionRecord:
    """Audit record for a single task in an orchestrated run.

    Attributes:
        task: The executed task (with its final status).
        result: The worker result returned for the task.
        verification: The verification verdict for the result.
    """

    task: DevelopmentTask
    result: WorkerResult
    verification: VerificationResult


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    """Outcome of a full autonomous development run.

    Attributes:
        objective: The objective that was planned and executed.
        tasks: Every planned task with its final status.
        executions: Audit records for the tasks that were executed.
        succeeded: Whether the run completed without a failed task.
        summary: Human-readable run summary.
    """

    objective: str
    tasks: tuple[DevelopmentTask, ...]
    executions: tuple[TaskExecutionRecord, ...]
    succeeded: bool
    summary: str


class DevelopmentOrchestrator:
    """Coordinate approval, planning, execution, verification, and review.

    The orchestrator owns the workflow: it plans an objective, schedules
    tasks in dependency order, dispatches each to a worker, verifies the
    worker result, and records an audit trail of every step.
    """

    def __init__(
        self,
        planner: DevelopmentPlanner | None = None,
        scheduler: DevelopmentScheduler | None = None,
        prompt_builder: PromptBuilder | None = None,
        worker: DevelopmentWorker | None = None,
        verifier: DevelopmentVerifier | None = None,
        reviewer: DevelopmentReviewer | None = None,
        worker_registry: WorkerRegistry | None = None,
    ) -> None:
        """Initialize the orchestrator with in-memory defaults when omitted.

        Args:
            worker_registry: When provided, each task is dispatched to the
                worker matching its ``worker`` type. A task whose CLI is
                not installed is blocked instead of executed. When omitted
                every task uses ``worker`` (defaults to ``MockWorker``).
        """
        self._planner = planner or DevelopmentPlanner()
        self._scheduler = scheduler or DevelopmentScheduler()
        self._prompt_builder = prompt_builder or PromptBuilder()
        self._worker = worker or MockWorker()
        self._verifier = verifier or DevelopmentVerifier()
        self._reviewer = reviewer
        self._worker_registry = worker_registry

    def plan(self, objective: str) -> tuple[DevelopmentTask, ...]:
        """Plan an objective without executing it."""
        return self._planner.plan(objective)

    def run(
        self,
        objective: str,
        worker_type: WorkerType | None = None,
    ) -> OrchestrationResult:
        """Plan and execute ``objective`` end to end.

        Args:
            objective: Objective to plan and execute.
            worker_type: Optional worker override applied to every planned
                task before scheduling.

        Returns:
            An orchestration result with the full audit trail.

        Raises:
            ValueError: If the objective is blank.
        """
        planned = self._planner.plan(objective)
        if not planned:
            return OrchestrationResult(
                objective=objective,
                tasks=(),
                executions=(),
                succeeded=True,
                summary="No work was planned for the objective.",
            )
        return self._execute(objective, planned, worker_type)

    def _execute(
        self,
        objective: str,
        planned: tuple[DevelopmentTask, ...],
        worker_type: WorkerType | None = None,
    ) -> OrchestrationResult:
        """Execute every eligible task in scheduler order."""
        if worker_type is not None:
            for task in planned:
                task.worker = worker_type

        executions: list[TaskExecutionRecord] = []
        halted = False
        halt_reason: str | None = None

        while True:
            task = self._scheduler.select_next(planned)
            if task is None:
                break

            if not self._approve(task):
                task.status = TaskStatus.BLOCKED
                halted = True
                halt_reason = "a task was not approved"
                break

            task.status = TaskStatus.RUNNING
            prompt = self._prompt_builder.build(task)
            try:
                worker = self._worker_for(task)
            except WorkerUnavailableError as exc:
                task.status = TaskStatus.BLOCKED
                halted = True
                halt_reason = str(exc)
                result = WorkerResult(success=False, summary=str(exc), output=str(exc))
                verification = VerificationResult(
                    passed=False,
                    summary=str(exc),
                    checks=(str(exc),),
                )
                executions.append(
                    TaskExecutionRecord(task=task, result=result, verification=verification)
                )
                break

            result = worker.execute(prompt)
            verification = self._verifier.verify(task, result)

            if verification.passed:
                task.status = TaskStatus.COMPLETED
            else:
                task.status = TaskStatus.FAILED
                halted = True

            if self._reviewer is not None:
                self._reviewer.review(task)

            executions.append(
                TaskExecutionRecord(task=task, result=result, verification=verification)
            )
            if halted:
                break

        if halted:
            for task in planned:
                if task.status is TaskStatus.PENDING:
                    task.status = TaskStatus.BLOCKED
            reason = halt_reason or "a task failed or was not approved"
            return OrchestrationResult(
                objective=objective,
                tasks=planned,
                executions=tuple(executions),
                succeeded=False,
                summary=f"Execution halted: {reason}; remaining work is blocked.",
            )

        return OrchestrationResult(
            objective=objective,
            tasks=planned,
            executions=tuple(executions),
            succeeded=True,
            summary=f"Executed and verified {len(executions)} task(s) for the objective.",
        )

    def _worker_for(self, task: DevelopmentTask) -> DevelopmentWorker:
        """Resolve the worker that should execute ``task``.

        With a worker registry configured, the task's ``worker`` type is
        resolved to its installed CLI worker. If that CLI is not
        installed, a :class:`WorkerUnavailableError` is raised so the run
        fails loudly instead of silently pretending to work. Without a
        registry, the configured worker (default ``MockWorker``) is used.
        """
        if self._worker_registry is not None:
            worker = self._worker_registry.get(task.worker)
            if worker is not None:
                return worker
            raise WorkerUnavailableError(
                f"{task.worker.value} worker is unavailable: the {task.worker.value} CLI is not installed"
            )
        return self._worker

    def _approve(self, task: DevelopmentTask) -> bool:
        """Approval checkpoint for a scheduled task.

        The default policy auto-approves every task. Subclasses or callers
        can supply a policy that gates execution on external approval.
        """
        return True
