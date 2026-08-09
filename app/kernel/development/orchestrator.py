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
from app.kernel.development.worker import DevelopmentWorker, LLMWorker, MockWorker


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
        use_llm_worker: bool = False,
        llm_model: str = "gpt-4",
    ) -> None:
        self.backlog = backlog or Backlog()
        self.scheduler = scheduler or DevelopmentScheduler()
        self.planner = planner or DevelopmentPlanner()
        self.prompt_builder = prompt_builder or PromptBuilder()
        
        # Initialize Git manager first as other components may need it
        self.git_manager = git_manager or GitManager(Path.cwd())
        
        # Initialize worker with Git manager
        if worker is not None:
            self.worker = worker
        elif use_llm_worker:
            self.worker = LLMWorker(model=llm_model, git_manager=self.git_manager)
        else:
            self.worker = MockWorker()
        
        # Initialize verifier and reviewer with Git manager
        self.verifier = verifier or DevelopmentVerifier(git_manager=self.git_manager)
        self.reviewer = reviewer or DevelopmentReviewer(git_manager=self.git_manager)
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
            # Plan the task
            plan = self.planner.plan(selected.description)
            
            # Build prompt with context
            prompt = self.prompt_builder.build(selected)
            
            # Execute with worker
            worker_result = self.worker.execute(prompt)
            if not worker_result.success:
                return self._failed(selected, worker_result.summary, worker_result=worker_result)

            # Stage modified files
            if worker_result.modified_files and self.git_manager:
                self.git_manager.stage_files(worker_result.modified_files)

            # Verify implementation
            verification_result = self.verifier.verify(selected)
            if not self._passed(verification_result, "passed"):
                return self._failed(
                    selected,
                    self._summary(verification_result, "Verification failed."),
                    worker_result=worker_result,
                    verification_result=verification_result,
                )

            # Review implementation
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

            # Commit changes
            git_status = None
            if self.git_manager:
                commit_msg = f"feat: {selected.description[:50]}"
                if self.git_manager.commit(commit_msg):
                    git_status = self.git_manager.inspect_status()

            # Remember successful completion
            self.memory.remember(
                str(selected.id),
                {"task": selected, "worker_result": worker_result},
            )
            selected.status = TaskStatus.COMPLETED
            return DevelopmentRunResult(
                RunStatus.COMPLETED,
                selected,
                "Task completed successfully.",
                worker_result,
                verification_result,
                review_result,
                git_status,
            )
        except Exception as error:
            return self._failed(selected, str(error) or type(error).__name__)

    def run_continuous(self, max_tasks: int = 10) -> list[DevelopmentRunResult]:
        """Run multiple tasks from backlog until empty or max reached."""
        results = []
        for _ in range(max_tasks):
            result = self.run()
            results.append(result)
            if result.status in (RunStatus.EMPTY, RunStatus.FAILED):
                break
        return results

    @staticmethod
    def _passed(result: object, attribute: str) -> bool:
        """Support explicit result models and simple boolean adapters."""

        if isinstance(result, bool):
            return result
        return bool(getattr(result, attribute, result is None))

    @staticmethod
    def _summary(result: object, fallback: str) -> str:
        return str(getattr(result, "summary", fallback))

    def _failed(
        self,
        task: DevelopmentTask,
        message: str,
        worker_result: object | None = None,
        verification_result: object | None = None,
        review_result: object | None = None,
    ) -> DevelopmentRunResult:
        task.status = TaskStatus.FAILED
        return DevelopmentRunResult(
            RunStatus.FAILED,
            task,
            message,
            worker_result,
            verification_result,
            review_result,
        )
