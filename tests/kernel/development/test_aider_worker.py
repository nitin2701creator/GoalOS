"""Tests for the Aider development worker."""

from __future__ import annotations

from unittest.mock import Mock

from app.kernel.development.worker import DevelopmentWorker, WorkerResult
from app.kernel.development.workers.aider_worker import AiderWorker
from app.kernel.development.workers.cli_worker import CLIWorker
from app.kernel.development.workers.subprocess_worker import SubprocessWorker


def test_aider_worker_implements_development_worker() -> None:
    """The worker satisfies the common development-worker interface."""

    assert isinstance(AiderWorker(), DevelopmentWorker)
    assert isinstance(AiderWorker(), CLIWorker)


def test_execute_runs_aider_with_prompt_through_subprocess_worker() -> None:
    """Aider commands are delegated to the existing subprocess worker."""

    expected_result = WorkerResult(
        success=True,
        summary="Command completed successfully.",
        output="Aider completed the change.",
    )
    subprocess_worker = Mock(spec=SubprocessWorker)
    subprocess_worker.execute.return_value = expected_result

    result = AiderWorker(subprocess_worker=subprocess_worker).execute(
        "Implement the requested change."
    )

    assert isinstance(result, WorkerResult)
    assert result is expected_result
    subprocess_worker.execute.assert_called_once_with(
        'aider --message "Implement the requested change."'
    )


def test_execute_quotes_prompts_with_spaces_and_quotes() -> None:
    """Prompts remain a single argument when forwarded to Aider."""

    subprocess_worker = Mock(spec=SubprocessWorker)
    subprocess_worker.execute.return_value = WorkerResult(True, "Done.", "")

    AiderWorker(subprocess_worker=subprocess_worker).execute('Update "app.py" safely.')

    subprocess_worker.execute.assert_called_once_with(
        'aider --message "Update \\"app.py\\" safely."'
    )
