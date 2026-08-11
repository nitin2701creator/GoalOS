"""Autonomous development loop for the Autonomous Development System.

The loop turns a development objective into a verified, committed
implementation by driving the existing ADS boundaries through a persisted
state machine::

    PLANNING -> IMPLEMENTING -> TESTING
        -> (FIXING -> IMPLEMENTING -> TESTING)*
        -> REVIEWING
        -> (FIXING -> IMPLEMENTING -> TESTING -> REVIEWING)*
        -> COMMITTING -> COMPLETED

Every state transition is observable through the ``on_state`` callback so
callers can persist the run. A bounded attempt limit guarantees the
repair cycle terminates, and the repository is only ever committed after
verification and review both pass — a failed run never commits and
therefore preserves the repository's committed state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from app.compat import StrEnum
from app.developer.repository_reader import RepositoryReader
from app.kernel.development.executors import CodingExecutor
from app.kernel.development.git_manager import GitManager
from app.kernel.development.models import DevelopmentTask
from app.kernel.development.prompt_builder import PromptBuilder
from app.kernel.development.reviewer import DevelopmentReviewer, ReviewResult
from app.kernel.development.test_runner import DevelopmentTestRunner, TestRun
from app.kernel.development.verifier import DevelopmentVerifier, VerificationResult
from app.kernel.development.worker import (
    DevelopmentWorker,
    WorkerResult,
    WorkerUnavailableError,
)


class AutonomousState(StrEnum):
    """Persisted lifecycle states of an autonomous development run."""

    PLANNING = "PLANNING"
    IMPLEMENTING = "IMPLEMENTING"
    TESTING = "TESTING"
    FIXING = "FIXING"
    REVIEWING = "REVIEWING"
    COMMITTING = "COMMITTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class InspectionResult:
    """Repository inspection that scopes an objective to candidate files.

    Attributes:
        files: Repository-relative paths the implementation may change.
        layers: Matched repository layers that drove the file selection.
        summary: Human-readable plan produced from the inspection.
    """

    files: tuple[Path, ...]
    layers: tuple[str, ...] = ()
    summary: str = ""


class RepositoryInspector:
    """Inspect a repository and scope an objective to candidate files.

    The inspector is deterministic and read-only: it discovers the
    repository's Python modules and targets files by matching objective
    keywords against layer directories (API, data, tests). An objective
    with no layer keywords falls back to the full module set so the
    worker retains a safe scope over the repository.
    """

    _API_TERMS = ("api", "endpoint", "route", "http")
    _DATA_TERMS = ("model", "database", "persist", "storage")
    _TEST_TERMS = ("test", "verify", "check", "suite")

    def __init__(self, repository: Path, reader: RepositoryReader | None = None) -> None:
        """Create an inspector rooted at ``repository``.

        Args:
            repository: Repository root to inspect.
            reader: Optional pre-built repository reader.
        """
        self.repository = Path(repository)
        self._reader = reader or RepositoryReader(self.repository)

    def inspect(self, objective: str) -> InspectionResult:
        """Return the file scope and plan summary for ``objective``."""
        modules = self._reader.python_modules()
        relative = [self._reader.relative_path(module) for module in modules]
        text = objective.lower()

        targets: list[Path] = []
        layers: list[str] = []

        if any(term in text for term in self._API_TERMS):
            api_files = [path for path in relative if any(part == "api" for part in path.parts)]
            if api_files:
                targets.extend(api_files)
                layers.append("api")

        if any(term in text for term in self._DATA_TERMS):
            data_files = [
                path
                for path in relative
                if any(part in ("db", "models", "repositories") for part in path.parts)
            ]
            if data_files:
                targets.extend(data_files)
                layers.append("data")

        if any(term in text for term in self._TEST_TERMS):
            test_files = [path for path in relative if "test" in path.as_posix().lower()]
            if test_files:
                targets.extend(test_files)
                layers.append("tests")

        if not targets:
            targets = list(relative)
            layers.append("repository")

        files = tuple(dict.fromkeys(targets))
        return InspectionResult(
            files=files,
            layers=tuple(layers),
            summary=self._summarize(objective, tuple(layers), files),
        )

    @staticmethod
    def _summarize(
        objective: str,
        layers: tuple[str, ...],
        files: tuple[Path, ...],
    ) -> str:
        """Build a human-readable plan from the matched layers and files."""
        scope = ", ".join(path.as_posix() for path in files) or "no python modules found"
        layer_text = ", ".join(layers) or "repository"
        return (
            f"Plan for '{objective}': target the {layer_text} layer(s) "
            f"({len(files)} file(s) in scope: {scope})."
        )


@dataclass(slots=True)
class AutonomousRunRecord:
    """Persisted-state view of one autonomous run.

    Attributes:
        objective: The development objective being executed.
        state: Current autonomous lifecycle state.
        task: The kernel task built from the objective and inspection.
        plan_summary: Repository-inspection plan for the objective.
        files: Repository-relative files in scope for the implementation.
        attempts: Number of implementation runs performed so far.
        test_runs: Every test-suite run in execution order.
        errors: Accumulated failure messages from any phase.
        review_results: Every review verdict in execution order.
        final_result: The worker result of the final implementation run.
        final_verification: The verification verdict of the final result.
        commit_hash: Hash of the verification-gated commit, if committed.
    """

    objective: str
    state: AutonomousState = AutonomousState.PLANNING
    task: DevelopmentTask | None = None
    plan_summary: str = ""
    files: list[Path] = field(default_factory=list)
    attempts: int = 0
    test_runs: list[TestRun] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    review_results: list[ReviewResult] = field(default_factory=list)
    final_result: WorkerResult | None = None
    final_verification: VerificationResult | None = None
    commit_hash: str | None = None


class AutonomousLoop:
    """Drive an objective through the full autonomous development loop.

    The loop composes the existing ADS boundaries: repository inspection
    (file scoping), a development worker (implementation), a test runner,
    the verifier and reviewer (quality gates), and the git manager
    (verification-gated commit). It never commits work that failed
    verification or review, and the attempt limit guarantees termination.
    """

    def __init__(
        self,
        worker: DevelopmentWorker,
        verifier: DevelopmentVerifier | None = None,
        reviewer: DevelopmentReviewer | None = None,
        git_manager: GitManager | None = None,
        test_runner: DevelopmentTestRunner | None = None,
        inspector: RepositoryInspector | None = None,
        executor: CodingExecutor | None = None,
        repository: Path | None = None,
        max_attempts: int = 3,
        on_state: Callable[[AutonomousState, AutonomousRunRecord], None] | None = None,
    ) -> None:
        """Initialize the loop with its boundaries and safety limits.

        Args:
            worker: Fallback worker used when no executor is configured.
            executor: Coding executor that implements the objective in
                the repository (e.g. the native GoalOS executor or the
                optional Aider adapter); when provided it takes
                precedence over ``worker``.
            verifier: Kernel verification strategy (default verifier).
            reviewer: Kernel review strategy (default reviewer).
            git_manager: Repository boundary used for the final commit;
                when omitted, the commit phase is skipped.
            test_runner: Test-suite executor (default runner).
            inspector: Repository inspector used for planning; when
                ``repository`` is given and ``inspector`` is omitted, a
                default inspector is created.
            repository: Repository root for inspection and test runs.
            max_attempts: Hard bound on implementation runs; reaching it
                with a failing test run fails the loop.
            on_state: Optional callback invoked after every state
                transition with the new state and the current record.
        """
        self.executor = executor
        self.worker = worker
        self.verifier = verifier or DevelopmentVerifier()
        self.reviewer = reviewer or DevelopmentReviewer()
        self.git_manager = git_manager
        self.test_runner = test_runner or DevelopmentTestRunner()
        self.repository = Path(repository) if repository is not None else None
        self.inspector = inspector or (
            RepositoryInspector(self.repository) if self.repository is not None else None
        )
        self.max_attempts = max_attempts
        self.on_state = on_state
        self._prompt_builder = PromptBuilder()

    def run(self, objective: str) -> AutonomousRunRecord:
        """Execute ``objective`` through the autonomous state machine.

        Args:
            objective: Development objective to implement, test, review,
                and commit.

        Returns:
            The persisted-state record of the run, ending in either
            ``COMPLETED`` or ``FAILED``.

        Raises:
            ValueError: If the objective is blank.
        """
        normalized = objective.strip()
        if not normalized:
            raise ValueError("Objective must not be empty")
        record = AutonomousRunRecord(objective=normalized)
        self._notify(record)

        inspection = self._plan(record)
        if inspection is None:
            return record

        record.task = DevelopmentTask(
            title=normalized,
            description=normalized,
            files=list(inspection.files),
        )
        record.files = list(inspection.files)
        record.plan_summary = inspection.summary
        record.state = AutonomousState.IMPLEMENTING
        self._notify(record)

        while record.state not in (AutonomousState.COMPLETED, AutonomousState.FAILED):
            if record.state is AutonomousState.IMPLEMENTING:
                self._implement(record)
            elif record.state is AutonomousState.TESTING:
                self._test(record)
            elif record.state is AutonomousState.FIXING:
                record.state = AutonomousState.IMPLEMENTING
                self._notify(record)
            elif record.state is AutonomousState.REVIEWING:
                self._review(record)
            elif record.state is AutonomousState.COMMITTING:
                self._commit(record)
            else:  # pragma: no cover - every state is handled above
                raise RuntimeError(f"unhandled autonomous state: {record.state}")

        return record

    def _plan(self, record: AutonomousRunRecord) -> InspectionResult | None:
        """Run the planning phase; returns ``None`` after failing the run."""
        if self.inspector is None:
            return self._fail(record, "no repository inspector configured for planning")
        try:
            return self.inspector.inspect(record.objective)
        except Exception as exc:  # noqa: BLE001 - inspection failure must fail the run
            return self._fail(record, f"repository inspection failed: {exc}")

    def _implement(self, record: AutonomousRunRecord) -> None:
        """Run the worker once; a bounded repair loop surrounds this phase."""
        if record.attempts >= self.max_attempts:
            self._fail(
                record,
                f"maximum attempts reached ({self.max_attempts}) without a passing test run",
            )
            return

        task = record.task
        if task is None:  # pragma: no cover - planning always builds the task first
            self._fail(record, "no task was planned")
            return

        if self.executor is not None:
            if not self.executor.available():
                self._fail(record, f"{self.executor.name} executor is unavailable")
                return
            try:
                result = self.executor.execute(
                    task, self.repository, feedback=self._feedback_text(record)
                )
            except Exception as exc:  # noqa: BLE001 - a crashing executor must fail the run
                self._fail(record, f"executor crashed: {exc}")
                return
            failure_label = "executor"
        else:
            prompt = self._build_prompt(task, record)
            try:
                result = self.worker.execute(prompt)
            except WorkerUnavailableError as exc:
                self._fail(record, str(exc))
                return
            except Exception as exc:  # noqa: BLE001 - a crashing worker must fail the run
                self._fail(record, f"worker crashed: {exc}")
                return
            failure_label = "worker"

        record.attempts += 1
        record.final_result = result
        if not result.success:
            record.errors.append(f"{failure_label} did not succeed: {result.summary}")
            record.state = AutonomousState.FIXING
        else:
            record.state = AutonomousState.TESTING
        self._notify(record)

    def _test(self, record: AutonomousRunRecord) -> None:
        """Run the repository's test suite against the latest implementation."""
        task = record.task
        if task is None:  # pragma: no cover - planning always builds the task first
            self._fail(record, "no task was planned")
            return

        test_run = self.test_runner.run(task.test_command, cwd=self.repository)
        record.test_runs.append(test_run)
        if test_run.passed:
            record.state = AutonomousState.REVIEWING
        else:
            record.errors.append(
                f"tests failed after attempt {record.attempts}: {test_run.summary()}"
            )
            record.state = AutonomousState.FIXING
        self._notify(record)

    def _review(self, record: AutonomousRunRecord) -> None:
        """Run the verifier and reviewer against the latest result."""
        task = record.task
        result = record.final_result
        if task is None or result is None:
            verification = VerificationResult(
                passed=False,
                summary="no worker result to verify",
                checks=("no worker result",),
            )
        else:
            verification = self.verifier.verify(task, result)

        test_run = record.test_runs[-1] if record.test_runs else None
        review = self.reviewer.review(task, result, test_run)

        record.final_verification = verification
        record.review_results.append(review)

        if not verification.passed:
            record.errors.append(verification.summary)
            record.state = AutonomousState.FIXING
        elif not review.passed:
            record.errors.append(review.summary)
            record.state = AutonomousState.FIXING
        else:
            record.state = AutonomousState.COMMITTING
        self._notify(record)

    def _commit(self, record: AutonomousRunRecord) -> None:
        """Commit the verified implementation, or complete without one."""
        if self.git_manager is None or not self.git_manager.is_repository():
            record.state = AutonomousState.COMPLETED
            self._notify(record)
            return

        try:
            record.commit_hash = self.git_manager.commit(f"ADS: {record.objective}")
        except Exception as exc:  # noqa: BLE001 - a failed commit must fail the run
            self._fail(record, f"commit failed: {exc}")
            return

        record.state = AutonomousState.COMPLETED
        self._notify(record)

    def _build_prompt(self, task: DevelopmentTask, record: AutonomousRunRecord) -> str:
        """Build the worker prompt, appending repair feedback when present."""
        prompt = self._prompt_builder.build(task)
        feedback = self._feedback_text(record)
        if feedback:
            prompt += "\n\n" + feedback
        return prompt

    def _feedback_text(self, record: AutonomousRunRecord) -> str:
        """Compile repair feedback from failed attempts and reviews."""
        feedback: list[str] = []
        if record.errors:
            feedback.append("Previous attempt feedback:\n" + "\n".join(record.errors[-3:]))

        failed_reviews = [review for review in record.review_results if not review.passed]
        if failed_reviews:
            findings = "\n".join(
                finding for review in failed_reviews for finding in review.findings
            )
            feedback.append("Review findings to address:\n" + findings)

        return "\n\n".join(feedback)

    def _fail(self, record: AutonomousRunRecord, message: str) -> None:
        """Persist a failure message and move the run to FAILED."""
        record.errors.append(message)
        record.state = AutonomousState.FAILED
        self._notify(record)

    def _notify(self, record: AutonomousRunRecord) -> None:
        """Invoke the state-transition callback, if one is configured."""
        if self.on_state is not None:
            self.on_state(record.state, record)
