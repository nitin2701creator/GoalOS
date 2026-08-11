"""Verification boundary for the Autonomous Development System."""

from __future__ import annotations

from dataclasses import dataclass

from app.kernel.development.models import DevelopmentTask
from app.kernel.development.worker import WorkerResult


@dataclass(frozen=True, slots=True)
class VerificationResult:
    """Structured verdict for a task's worker result.

    Attributes:
        passed: Whether every verification check succeeded.
        summary: Human-readable verdict summary.
        checks: Individual failed checks, empty when the result passed.
    """

    passed: bool
    summary: str
    checks: tuple[str, ...] = ()


class DevelopmentVerifier:
    """Verify completed development work against deterministic criteria."""

    def verify(self, task: DevelopmentTask, result: WorkerResult) -> VerificationResult:
        """Check ``result`` against the task's expectations.

        Verification rules:

        - the worker must report success;
        - the worker must produce non-empty output; and
        - any reported modified file must be inside the task's declared
          file scope (tasks without a declared scope accept any files).

        Args:
            task: The task whose outcome is being verified.
            result: The worker result produced for the task.

        Returns:
            A structured verification verdict.
        """
        failed_checks: list[str] = []

        if not result.success:
            failed_checks.append("worker did not report success")
        if not result.output.strip():
            failed_checks.append("worker produced no output artifact")
        if task.files:
            allowed_files = set(task.files)
            out_of_scope = [path for path in result.modified_files if path not in allowed_files]
            if out_of_scope:
                out_of_scope_names = ", ".join(path.as_posix() for path in out_of_scope)
                failed_checks.append(f"modified files outside the declared scope: {out_of_scope_names}")

        if failed_checks:
            return VerificationResult(
                passed=False,
                summary="Verification failed: " + "; ".join(failed_checks) + ".",
                checks=tuple(failed_checks),
            )

        return VerificationResult(
            passed=True,
            summary="Verification passed: result satisfies the task expectations.",
        )
