"""Tests for one-task Autonomous Development System orchestration."""

from __future__ import annotations

from app.kernel.development.backlog import Backlog
from app.kernel.development.models import DevelopmentTask, RunStatus, TaskStatus
from app.kernel.development.orchestrator import DevelopmentOrchestrator
from app.kernel.development.reviewer import ReviewResult
from app.kernel.development.verifier import VerificationResult
from app.kernel.development.worker import DevelopmentWorker, WorkerResult


class RecordingScheduler:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def select_next(self, tasks: tuple[DevelopmentTask, ...]) -> DevelopmentTask | None:
        self.events.append("scheduler")
        return next((task for task in tasks if task.status is TaskStatus.PENDING), None)


class RecordingPlanner:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def plan(self, objective: str) -> tuple[DevelopmentTask, ...]:
        self.events.append("planner")
        return ()


class RecordingPromptBuilder:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def build(self, task: DevelopmentTask) -> str:
        self.events.append("prompt_builder")
        return task.title


class RecordingWorker(DevelopmentWorker):
    def __init__(self, events: list[str], success: bool = True) -> None:
        self.events = events
        self.success = success

    def execute(self, prompt: str) -> WorkerResult:
        self.events.append("worker")
        return WorkerResult(self.success, "Worker result.", "")


class RecordingVerifier:
    def __init__(self, events: list[str], passed: bool = True) -> None:
        self.events = events
        self.passed = passed

    def verify(self, task: DevelopmentTask) -> VerificationResult:
        self.events.append("verifier")
        return VerificationResult(self.passed, "Verification result.")


class RecordingReviewer:
    def __init__(self, events: list[str], approved: bool = True) -> None:
        self.events = events
        self.approved = approved

    def review(self, task: DevelopmentTask) -> ReviewResult:
        self.events.append("reviewer")
        return ReviewResult(self.approved, "Review result.")


class RecordingGitManager:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def inspect_status(self) -> str:
        self.events.append("git_manager")
        return "clean"


class RecordingMemory:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.entries: dict[str, object] = {}

    def remember(self, key: str, value: object) -> None:
        self.events.append("memory")
        self.entries[key] = value


def make_orchestrator(
    events: list[str], *, verification_passed: bool = True, review_approved: bool = True
) -> DevelopmentOrchestrator:
    return DevelopmentOrchestrator(
        backlog=Backlog(),
        scheduler=RecordingScheduler(events),
        planner=RecordingPlanner(events),
        prompt_builder=RecordingPromptBuilder(events),
        worker=RecordingWorker(events),
        verifier=RecordingVerifier(events, verification_passed),
        reviewer=RecordingReviewer(events, review_approved),
        git_manager=RecordingGitManager(events),
        memory=RecordingMemory(events),
    )


def test_successful_execution_coordinates_all_components() -> None:
    events: list[str] = []
    orchestrator = make_orchestrator(events)
    task = DevelopmentTask(title="Add orchestration", description="Coordinate ADS.")
    orchestrator.backlog.add(task)

    result = orchestrator.run()

    assert result.status is RunStatus.COMPLETED
    assert result.task is task
    assert task.status is TaskStatus.COMPLETED
    assert events == [
        "scheduler",
        "planner",
        "prompt_builder",
        "worker",
        "verifier",
        "reviewer",
        "git_manager",
        "memory",
    ]


def test_verification_failure_marks_task_failed_and_stops_pipeline() -> None:
    events: list[str] = []
    orchestrator = make_orchestrator(events, verification_passed=False)
    task = DevelopmentTask(title="Verify failure", description="Reject invalid work.")
    orchestrator.backlog.add(task)

    result = orchestrator.run()

    assert result.status is RunStatus.FAILED
    assert task.status is TaskStatus.FAILED
    assert events == ["scheduler", "planner", "prompt_builder", "worker", "verifier"]


def test_reviewer_rejection_blocks_task_and_stops_before_git() -> None:
    events: list[str] = []
    orchestrator = make_orchestrator(events, review_approved=False)
    task = DevelopmentTask(title="Review rejection", description="Reject scope creep.")
    orchestrator.backlog.add(task)

    result = orchestrator.run()

    assert result.status is RunStatus.REJECTED
    assert task.status is TaskStatus.BLOCKED
    assert events == ["scheduler", "planner", "prompt_builder", "worker", "verifier", "reviewer"]


def test_empty_backlog_returns_empty_result_without_running_components() -> None:
    events: list[str] = []
    orchestrator = make_orchestrator(events)

    result = orchestrator.run()

    assert result.status is RunStatus.EMPTY
    assert result.task is None
    assert events == ["scheduler"]
