"""Tests for the development application service."""

from __future__ import annotations

from app.kernel.development.backlog import Backlog
from app.kernel.development.models import DevelopmentTask, TaskStatus
from app.kernel.development.prompt_builder import PromptBuilder
from app.kernel.development.service import DevelopmentService
from app.kernel.development.worker import DevelopmentWorker, WorkerResult


class RecordingPromptBuilder(PromptBuilder):
    """Prompt builder that records the task it receives."""

    def __init__(self) -> None:
        self.tasks: list[DevelopmentTask] = []

    def build(self, task: DevelopmentTask) -> str:
        self.tasks.append(task)
        return f"prompt for {task.title}"


class RecordingWorker(DevelopmentWorker):
    """Worker that records prompts and returns predefined results."""

    def __init__(self, results: list[WorkerResult]) -> None:
        self.prompts: list[str] = []
        self.results = results

    def execute(self, prompt: str) -> WorkerResult:
        self.prompts.append(prompt)
        return self.results.pop(0)


def make_task(title: str) -> DevelopmentTask:
    """Create a development task for service tests."""

    return DevelopmentTask(title=title, description=f"{title} description.")


def make_service(results: list[WorkerResult]) -> tuple[DevelopmentService, RecordingPromptBuilder, RecordingWorker]:
    """Create a service and its observable collaborators."""

    builder = RecordingPromptBuilder()
    worker = RecordingWorker(results)
    return DevelopmentService(Backlog(), builder, worker), builder, worker


def test_empty_backlog_returns_none() -> None:
    """No work is executed when no task is pending."""

    service, builder, worker = make_service([])

    assert service.execute_next() is None
    assert builder.tasks == []
    assert worker.prompts == []


def test_add_task_stores_task_in_backlog() -> None:
    """Added tasks are retained by the supplied backlog."""

    backlog = Backlog()
    service = DevelopmentService(backlog)
    task = make_task("Add service")

    service.add_task(task)

    assert backlog.list() == [task]


def test_execute_next_builds_prompt_and_executes_worker() -> None:
    """The task flows from the builder into the worker as its prompt."""

    result = WorkerResult(success=True, summary="Done.", output="")
    service, builder, worker = make_service([result])
    task = make_task("Build prompt")
    service.add_task(task)

    assert service.execute_next() is result
    assert builder.tasks == [task]
    assert worker.prompts == ["prompt for Build prompt"]


def test_execute_next_returns_worker_result_unchanged() -> None:
    """The worker result is returned without replacement or modification."""

    result = WorkerResult(success=False, summary="Blocked.", output="Details.")
    service, _, _ = make_service([result])
    service.add_task(make_task("Return result"))

    assert service.execute_next() is result


def test_multiple_pending_tasks_execute_in_insertion_order() -> None:
    """Each call selects the oldest still-pending task."""

    first_result = WorkerResult(success=True, summary="First.", output="")
    second_result = WorkerResult(success=True, summary="Second.", output="")
    service, builder, worker = make_service([first_result, second_result])
    first_task = make_task("First")
    second_task = make_task("Second")
    service.add_task(first_task)
    service.add_task(second_task)

    service.execute_next()
    first_task.status = TaskStatus.COMPLETED
    service.execute_next()

    assert builder.tasks == [first_task, second_task]
    assert worker.prompts == ["prompt for First", "prompt for Second"]
