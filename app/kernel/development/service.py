"""Application service for development task execution."""

from __future__ import annotations

from app.kernel.development.backlog import Backlog
from app.kernel.development.models import DevelopmentTask
from app.kernel.development.prompt_builder import PromptBuilder
from app.kernel.development.worker import DevelopmentWorker, MockWorker, WorkerResult


class DevelopmentService:
    """Coordinate pending development tasks with a prompt builder and worker."""

    def __init__(
        self,
        backlog: Backlog | None = None,
        prompt_builder: PromptBuilder | None = None,
        worker: DevelopmentWorker | None = None,
    ) -> None:
        """Initialize the service with in-memory defaults when omitted."""

        self.backlog = backlog or Backlog()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.worker = worker or MockWorker()

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
