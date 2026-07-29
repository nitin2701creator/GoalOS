"""Tests for Autonomous Development System worker abstractions."""

from __future__ import annotations

from app.kernel.development.worker import DevelopmentWorker, MockWorker, WorkerResult


def test_mock_worker_implements_development_worker() -> None:
    """The mock worker satisfies the common worker interface."""

    assert isinstance(MockWorker(), DevelopmentWorker)


def test_execute_returns_worker_result() -> None:
    """Mock execution returns the common result type."""

    result = MockWorker().execute("Implement the model.")

    assert isinstance(result, WorkerResult)


def test_execute_preserves_prompt_and_succeeds() -> None:
    """Mock execution records and returns the received prompt."""

    worker = MockWorker()
    prompt = "Implement only the requested module."

    result = worker.execute(prompt)

    assert worker.prompt == prompt
    assert result.success is True
    assert result.summary == "Mock execution completed."
    assert result.output == prompt


def test_worker_result_defaults_modified_files_to_empty_list() -> None:
    """Worker results do not share mutable modified-file defaults."""

    result = WorkerResult(success=True, summary="Done.", output="")

    assert result.modified_files == []
