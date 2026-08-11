"""Application service for development task execution."""

from __future__ import annotations

from app.kernel.development.backlog import Backlog
from app.kernel.development.models import DevelopmentTask, WorkerType
from app.kernel.development.orchestrator import (
    DevelopmentOrchestrator,
    OrchestrationResult,
)
from app.kernel.development.planner import DevelopmentPlanner
from app.kernel.development.prompt_builder import PromptBuilder
from app.kernel.development.scheduler import DevelopmentScheduler
from app.kernel.development.verifier import DevelopmentVerifier
from app.kernel.development.worker import (
    DevelopmentWorker,
    MockWorker,
    WorkerRegistry,
    WorkerResult,
)


class DevelopmentService:
    """Coordinate pending development tasks and autonomous objective runs.

    The service exposes two paths:

    - ``add_task``/``execute_next``: classic backlog-driven execution where
      a caller submits tasks and drains them one at a time; and
    - ``run_objective``/``preview_objective``: end-to-end autonomous
      planning, scheduling, execution, and verification of an objective.
    """

    def __init__(
        self,
        backlog: Backlog | None = None,
        prompt_builder: PromptBuilder | None = None,
        worker: DevelopmentWorker | None = None,
        planner: DevelopmentPlanner | None = None,
        scheduler: DevelopmentScheduler | None = None,
        verifier: DevelopmentVerifier | None = None,
        orchestrator: DevelopmentOrchestrator | None = None,
        worker_registry: WorkerRegistry | None = None,
    ) -> None:
        """Initialize the service with in-memory defaults when omitted.

        Args:
            worker_registry: When provided, the orchestrator dispatches
                each task to the CLI worker matching its ``worker`` type
                and blocks tasks whose CLI is not installed.
        """
        self.backlog = backlog or Backlog()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.worker = worker or MockWorker()
        self.orchestrator = orchestrator or DevelopmentOrchestrator(
            planner=planner,
            scheduler=scheduler,
            prompt_builder=self.prompt_builder,
            worker=self.worker,
            verifier=verifier,
            worker_registry=worker_registry,
        )

    def add_task(self, task: DevelopmentTask) -> None:
        """Add ``task`` to the backlog."""
        self.backlog.add(task)

    def execute_next(self) -> WorkerResult | None:
        """Execute the first pending task without changing its status."""
        task = self.backlog.next_task()
        if task is None:
            return None

        prompt = self.prompt_builder.build(task)
        return self.worker.execute(prompt)

    def preview_objective(self, objective: str) -> OrchestrationResult:
        """Plan an objective without executing any work."""
        planned = self.orchestrator.plan(objective)
        return OrchestrationResult(
            objective=objective,
            tasks=planned,
            executions=(),
            succeeded=True,
            summary="Plan generated for preview; no work was executed.",
        )

    def run_objective(
        self,
        objective: str,
        worker_type: WorkerType | None = None,
    ) -> OrchestrationResult:
        """Plan, schedule, execute, and verify an objective end to end.

        Args:
            objective: Objective to plan and execute.
            worker_type: Optional worker override applied to every planned
                task before scheduling.
        """
        return self.orchestrator.run(objective, worker_type)
