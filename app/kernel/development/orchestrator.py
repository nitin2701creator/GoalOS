"""Orchestration boundary for the Autonomous Development System."""

from __future__ import annotations

from pathlib import Path

from app.kernel.development.backlog import Backlog
from app.kernel.development.git_manager import GitManager
from app.kernel.development.memory import DevelopmentMemory
from app.kernel.development.models import (
    DevelopmentRunResult,
    DevelopmentTask,
    RunStatus,
    TaskStatus,
)
from app.kernel.development.planner import DevelopmentPlanner
from app.kernel.development.prompt_builder import PromptBuilder
from app.kernel.development.reviewer import DevelopmentReviewer
from app.kernel.development.scheduler import DevelopmentScheduler
from app.kernel.development.verifier import DevelopmentVerifier
from app.kernel.development.worker import DevelopmentWorker, MockWorker


class DevelopmentOrchestrator:
    """Coordinate one task through the ADS lifecycle."""

    def __init__(
        self,
        backlog: Backlog | None = None,
        scheduler: DevelopmentScheduler | None = None,
        planner: DevelopmentPlanner | None = None,
        prompt_builder: PromptBuilder | None = None,
        worker: DevelopmentWorker | None = None,
        verifier: DevelopmentVerifier | None = None,
        reviewer: DevelopmentReviewer | None = None,
        git_manager: GitManager | None = None,
        memory: DevelopmentMemory | None = None,
    ) -> None:
        self.backlog = backlog or Backlog()
        self.scheduler = scheduler or DevelopmentScheduler()
        self.planner = planner or DevelopmentPlanner()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.worker = worker or MockWorker()
        self.verifier = verifier or DevelopmentVerifier()
        self.reviewer = reviewer or DevelopmentReviewer()
        self.git_manager = git_manager or GitManager(Path.cwd())
        self.memory = memory or DevelopmentMemory()

    def run(self, task: DevelopmentTask | None = None) -> DevelopmentRunResult:
        """Execute exactly one task, stopping at the first failed gate."""

        if task is not None and self.backlog.get(task.id) is None:
            self.backlog.add(task)

        candidates = (task,) if task is not None else tuple(self.backlog.list())
        selected = self.scheduler.select_next(candidates)
        if selected is None:
            return DevelopmentRunResult(RunStatus.EMPTY, message="No pending development task.")

        selected.status = TaskStatus.RUNNING
        try:
            self.planner.plan(selected.description)
            prompt = self.prompt_builder.build(selected)
            worker_result = self.worker.execute(prompt)
            if not worker_result.success:
                return self._failed(selected, worker_result.summary, worker_result=worker_result)

            verification_result = self.verifier.verify(selected)
            if not self._passed(verification_result, "passed"):
                return self._failed(
                    selected,
                    self._summary(verification_result, "Verification failed."),
                    worker_result=worker_result,
                    verification_result=verification_result,
                )

            review_result = self.reviewer.review(selected)
            if not self._passed(review_result, "approved"):
                selected.status = TaskStatus.BLOCKED
                return DevelopmentRunResult(
                    RunStatus.REJECTED,
                    selected,
                    self._summary(review_result, "Review rejected."),
                    worker_result,
                    verification_result,
                    review_result,
                )

            git_status = self.git_manager.inspect_status()
            self.memory.remember(
                str(selected.id),
                {"task": selected, "worker_result": worker_result},
            )
            selected.status = TaskStatus.COMPLETED
            return DevelopmentRunResult(
                RunStatus.COMPLETED,
                selected,
                "Task completed.",
                worker_result,
                verification_result,
                review_result,
                git_status,
            )
        except Exception as error:
            return self._failed(selected, str(error) or type(error).__name__)

    @staticmethod
    def _passed(result: object, attribute: str) -> bool:
        """Support explicit result models and simple boolean adapters."""

        if isinstance(result, bool):
            return result
        return bool(getattr(result, attribute, result is None))

    @staticmethod
    def _summary(result: object, fallback: str) -> str:
        return str(getattr(result, "summary", fallback))

    @staticmethod
    def _failed(
        task: DevelopmentTask,
        message: str,
        worker_result: object | None = None,
        verification_result: object | None = None,
    ) -> DevelopmentRunResult:
        task.status = TaskStatus.FAILED
        return DevelopmentRunResult(
            RunStatus.FAILED,
            task,
            message,
            worker_result,
            verification_result,
        )


# TODO: Add explicit orchestration state and lifecycle events.
