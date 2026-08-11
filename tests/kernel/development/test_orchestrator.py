"""Tests for the ADS orchestrator and service end-to-end execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.kernel.development.models import DevelopmentTask, TaskStatus, WorkerType
from app.kernel.development.orchestrator import DevelopmentOrchestrator
from app.kernel.development.prompt_builder import PromptBuilder
from app.kernel.development.reviewer import DevelopmentReviewer
from app.kernel.development.service import DevelopmentService
from app.kernel.development.worker import DevelopmentWorker, WorkerResult


class RecordingPromptBuilder(PromptBuilder):
    """Prompt builder that records the tasks it receives."""

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


class RecordingReviewer(DevelopmentReviewer):
    """Reviewer that records the tasks it reviews."""

    def __init__(self) -> None:
        self.tasks: list[DevelopmentTask] = []

    def review(self, task: DevelopmentTask) -> None:
        self.tasks.append(task)


def successful_result() -> WorkerResult:
    """A worker result that satisfies the verifier."""
    return WorkerResult(success=True, summary="Done.", output="Implemented the objective.")


def test_orchestrator_runs_pipeline_end_to_end() -> None:
    """Every planned task is executed, verified, and completed."""

    builder = RecordingPromptBuilder()
    worker = RecordingWorker([successful_result() for _ in range(4)])
    reviewer = RecordingReviewer()
    orchestrator = DevelopmentOrchestrator(
        prompt_builder=builder,
        worker=worker,
        reviewer=reviewer,
    )

    result = orchestrator.run("Add analytics module")

    assert result.succeeded
    assert len(result.tasks) == 4
    assert all(task.status is TaskStatus.COMPLETED for task in result.tasks)
    assert len(result.executions) == 4
    assert all(record.verification.passed for record in result.executions)
    assert len(builder.tasks) == 4
    assert len(worker.prompts) == 4
    assert len(reviewer.tasks) == 4


def test_orchestrator_executes_in_dependency_order() -> None:
    """Tasks run only after their dependencies complete."""

    worker = RecordingWorker([successful_result() for _ in range(4)])
    builder = RecordingPromptBuilder()
    orchestrator = DevelopmentOrchestrator(prompt_builder=builder, worker=worker)

    orchestrator.run("Reduce costs")

    titles = [task.title for task in builder.tasks]
    assert titles[0].startswith("Define requirements")
    assert titles[1].startswith("Implement")
    assert titles[2].startswith("Test")
    assert titles[3].startswith("Document")


def test_failed_task_halts_run_and_blocks_remaining() -> None:
    """A failed task fails the run and blocks the remaining work."""

    failure = WorkerResult(success=False, summary="Blocked.", output="")
    worker = RecordingWorker([failure])
    orchestrator = DevelopmentOrchestrator(worker=worker)

    result = orchestrator.run("Ship reporting")

    assert not result.succeeded
    assert result.executions[0].task.status is TaskStatus.FAILED
    assert len(result.executions) == 1
    remaining = [task for task in result.tasks if task.status is TaskStatus.PENDING]
    assert remaining == []
    assert any(task.status is TaskStatus.BLOCKED for task in result.tasks)


def test_rejected_verification_fails_task() -> None:
    """A worker result that fails verification fails its task."""

    worker = RecordingWorker(
        [WorkerResult(success=True, summary="Done.", output="", modified_files=[Path("README.md")])]
    )
    task = DevelopmentTask(title="Scoped task", description="Description.", files=[Path("app/a.py")])
    orchestrator = DevelopmentOrchestrator(worker=worker)

    result = orchestrator._execute("Scoped objective", (task,))

    assert not result.succeeded
    assert task.status is TaskStatus.FAILED
    assert "outside the declared scope" in result.executions[0].verification.summary


def test_run_rejects_blank_objective() -> None:
    """A blank objective raises a planning error."""

    with pytest.raises(ValueError, match="must not be empty"):
        DevelopmentOrchestrator().run("   ")


def test_service_run_objective_executes_end_to_end() -> None:
    """The service entry point runs the full pipeline."""

    result = DevelopmentService().run_objective("Add analytics module")

    assert result.succeeded
    assert len(result.tasks) == 4
    assert all(task.status is TaskStatus.COMPLETED for task in result.tasks)


def test_service_preview_objective_does_not_execute() -> None:
    """Preview plans work without executing any task."""

    result = DevelopmentService().preview_objective("Add analytics module")

    assert result.succeeded
    assert len(result.tasks) == 4
    assert result.executions == ()
    assert all(task.status is TaskStatus.PENDING for task in result.tasks)


def test_orchestrator_uses_registry_worker_for_task_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tasks dispatch to the CLI worker matching their worker type."""

    import subprocess

    from app.kernel.development.worker import WorkerRegistry

    monkeypatch.setattr(
        "app.kernel.development.worker.shutil.which", lambda _: "/usr/bin/codex"
    )
    prompts: list[str] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        prompts.append(command[-1])
        return subprocess.CompletedProcess(command, 0, "implemented", "")

    monkeypatch.setattr("app.kernel.development.worker.subprocess.run", fake_run)

    fallback = RecordingWorker([successful_result()])
    orchestrator = DevelopmentOrchestrator(
        worker=fallback,
        worker_registry=WorkerRegistry(),
    )

    result = orchestrator.run("Add analytics module", worker_type=WorkerType.CODEX)

    assert result.succeeded
    assert len(prompts) == 4
    assert fallback.prompts == []
    assert all(task.worker is WorkerType.CODEX for task in result.tasks)


def test_orchestrator_blocks_task_when_worker_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing CLI blocks the first task and halts the run loudly."""

    from app.kernel.development.worker import WorkerRegistry

    monkeypatch.setattr(
        "app.kernel.development.worker.shutil.which", lambda _: None
    )

    orchestrator = DevelopmentOrchestrator(
        worker=RecordingWorker([successful_result()]),
        worker_registry=WorkerRegistry(),
    )

    result = orchestrator.run("Add analytics module")

    assert not result.succeeded
    assert len(result.executions) == 1
    assert result.executions[0].task.status is TaskStatus.BLOCKED
    assert not result.executions[0].verification.passed
    assert "unavailable" in result.summary
    assert all(
        task.status in (TaskStatus.BLOCKED, TaskStatus.PENDING)
        for task in result.tasks
    )
