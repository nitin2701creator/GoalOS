"""Tests for the subprocess development worker."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

from app.kernel.development.worker import DevelopmentWorker, WorkerResult
from app.kernel.development.workers.subprocess_worker import SubprocessWorker


def test_subprocess_worker_implements_development_worker() -> None:
    """The worker satisfies the common development-worker interface."""

    assert isinstance(SubprocessWorker(), DevelopmentWorker)


@patch("app.kernel.development.workers.subprocess_worker.subprocess.run")
def test_execute_captures_successful_command_output(mock_run: object) -> None:
    """Successful commands return their captured standard output."""

    mock_run.return_value = subprocess.CompletedProcess(
        args="echo hello", returncode=0, stdout="hello\n", stderr=""
    )

    result = SubprocessWorker().execute("echo hello")

    assert isinstance(result, WorkerResult)
    assert result.success is True
    assert result.summary == "Command completed successfully."
    assert result.output == "hello\n"
    mock_run.assert_called_once_with(
        "echo hello", shell=True, capture_output=True, text=True, check=False
    )


@patch("app.kernel.development.workers.subprocess_worker.subprocess.run")
def test_execute_captures_stderr_and_nonzero_exit_code(mock_run: object) -> None:
    """Failed commands expose standard error and their exit code."""

    mock_run.return_value = subprocess.CompletedProcess(
        args="bad-command", returncode=3, stdout="partial\n", stderr="failed\n"
    )

    result = SubprocessWorker().execute("bad-command")

    assert result.success is False
    assert result.summary == "Command exited with code 3."
    assert result.output == "partial\nfailed\n"


@patch("app.kernel.development.workers.subprocess_worker.subprocess.run")
def test_execute_handles_os_errors(mock_run: object) -> None:
    """Execution errors return a failed result instead of raising."""

    mock_run.side_effect = OSError("process unavailable")

    result = SubprocessWorker().execute("echo hello")

    assert result.success is False
    assert result.summary == "Command execution failed."
    assert result.output == "process unavailable"
