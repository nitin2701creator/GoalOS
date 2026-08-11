"""Review boundary for the Autonomous Development System.

The reviewer is a second, deterministic quality gate that runs after the
test suite passes: it checks the worker result and the test outcome for
problems the autonomous loop can fix by re-running the worker. Findings
are deliberately bounded — the loop's attempt limit guarantees the
repair cycle terminates, and work that fails review is never committed.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.kernel.development.models import DevelopmentTask
from app.kernel.development.test_runner import TestRun
from app.kernel.development.worker import WorkerResult


@dataclass(frozen=True, slots=True)
class ReviewResult:
    """Structured verdict for a task's review.

    Attributes:
        passed: Whether every review check succeeded.
        findings: Individual fixable problems, empty when the result passed.
        summary: Human-readable verdict summary.
    """

    passed: bool
    findings: tuple[str, ...] = ()
    summary: str = ""


class DevelopmentReviewer:
    """Review ADS task outcomes against deterministic quality criteria."""

    def review(
        self,
        task: DevelopmentTask,
        result: WorkerResult | None = None,
        test_run: TestRun | None = None,
    ) -> ReviewResult:
        """Review ``result`` and ``test_run`` against the task expectations.

        Review rules:

        - the worker must report success and produce output;
        - when the task declares a file scope, the worker must change at
          least one file and every changed file must be in scope; and
        - the test run must have passed.

        Findings are fixable: the autonomous loop re-runs the worker with
        the review summary as feedback and re-tests (bounded attempts).

        Args:
            task: The task whose outcome is being reviewed.
            result: The worker result produced for the task.
            test_run: The test run performed against the result.

        Returns:
            A structured review verdict.
        """
        findings: list[str] = []

        if result is not None:
            if not result.success:
                findings.append("worker did not report success")
            if not result.output.strip():
                findings.append("worker produced no output artifact")
            if task.files:
                allowed = set(task.files)
                if not result.modified_files:
                    findings.append("implementation produced no file changes")
                else:
                    out_of_scope = [path for path in result.modified_files if path not in allowed]
                    if out_of_scope:
                        names = ", ".join(path.as_posix() for path in out_of_scope)
                        findings.append(f"modified files outside the declared scope: {names}")

        if test_run is not None and not test_run.passed:
            findings.append(f"tests did not pass: {test_run.command}")

        if findings:
            return ReviewResult(
                passed=False,
                findings=tuple(findings),
                summary="Review found issues: " + "; ".join(findings) + ".",
            )

        return ReviewResult(
            passed=True,
            summary="Review passed: implementation is in scope and the test suite passes.",
        )
