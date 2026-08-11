"""Tests for ADS verification rules."""

from __future__ import annotations

from pathlib import Path

from app.kernel.development.models import DevelopmentTask
from app.kernel.development.verifier import DevelopmentVerifier
from app.kernel.development.worker import WorkerResult


def make_task(files: list[Path] | None = None) -> DevelopmentTask:
    """Create a development task for verifier tests."""
    return DevelopmentTask(title="Task", description="Description.", files=files or [])


def test_accepts_successful_result_with_output() -> None:
    """A successful worker result with output passes verification."""

    result = WorkerResult(success=True, summary="Done.", output="Implemented the module.")

    verdict = DevelopmentVerifier().verify(make_task(), result)

    assert verdict.passed
    assert verdict.checks == ()


def test_rejects_failed_worker_result() -> None:
    """A failed worker result cannot pass verification."""

    result = WorkerResult(success=False, summary="Blocked.", output="Details.")

    verdict = DevelopmentVerifier().verify(make_task(), result)

    assert not verdict.passed
    assert "did not report success" in verdict.summary


def test_rejects_empty_output() -> None:
    """A successful worker that produced nothing is rejected."""

    result = WorkerResult(success=True, summary="Done.", output="   ")

    verdict = DevelopmentVerifier().verify(make_task(), result)

    assert not verdict.passed
    assert "no output" in verdict.summary


def test_rejects_out_of_scope_file_modifications() -> None:
    """Modifying files outside the declared scope fails verification."""

    task = make_task(files=[Path("app/kernel/development/models.py")])
    result = WorkerResult(
        success=True,
        summary="Done.",
        output="Implemented.",
        modified_files=[Path("app/kernel/development/models.py"), Path("README.md")],
    )

    verdict = DevelopmentVerifier().verify(task, result)

    assert not verdict.passed
    assert "outside the declared scope" in verdict.summary
    assert "README.md" in verdict.summary


def test_accepts_in_scope_file_modifications() -> None:
    """Modifying only declared files passes verification."""

    task = make_task(files=[Path("app/kernel/development/models.py")])
    result = WorkerResult(
        success=True,
        summary="Done.",
        output="Implemented.",
        modified_files=[Path("app/kernel/development/models.py")],
    )

    assert DevelopmentVerifier().verify(task, result).passed


def test_checks_list_failed_rules() -> None:
    """The verdict exposes each failed check."""

    result = WorkerResult(success=False, summary="Blocked.", output="")

    verdict = DevelopmentVerifier().verify(make_task(), result)

    assert verdict.checks
    assert "worker did not report success" in verdict.checks
    assert "worker produced no output artifact" in verdict.checks
