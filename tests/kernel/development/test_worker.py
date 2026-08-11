"""Tests for Autonomous Development System worker abstractions."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.kernel.development.models import WorkerType
from app.kernel.development.worker import (
    AiderWorker,
    ClaudeWorker,
    CodexWorker,
    DevelopmentWorker,
    MockWorker,
    OpenHandsWorker,
    WorkerRegistry,
    WorkerResult,
    WorkerUnavailableError,
    create_worker,
)


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


# --- CLI workers -----------------------------------------------------------


def test_cli_worker_reports_unavailable_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing CLI executable makes the worker unavailable."""

    monkeypatch.setattr("app.kernel.development.worker.shutil.which", lambda _: None)

    worker = CodexWorker()

    assert worker.available() is False


def test_cli_worker_raises_when_binary_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Executing an unavailable worker raises a clear error."""

    monkeypatch.setattr("app.kernel.development.worker.shutil.which", lambda _: None)

    with pytest.raises(WorkerUnavailableError, match="codex is not installed"):
        CodexWorker().execute("Implement it.")


def test_cli_worker_raises_is_runtime_error() -> None:
    """The unavailable error is a runtime error."""

    assert issubclass(WorkerUnavailableError, RuntimeError)


@pytest.mark.parametrize(
    ("worker_type", "expected_command"),
    [
        (WorkerType.CODEX, ["codex", "exec", "Build it."]),
        (WorkerType.AIDER, ["aider", "--message", "Build it.", "--yes"]),
        (WorkerType.CLAUDE, ["claude", "-p", "Build it.", "--output-format", "text"]),
        (WorkerType.OPENHANDS, ["openhands", "run", "--task", "Build it."]),
    ],
)
def test_worker_builds_expected_cli_command(worker_type: WorkerType, expected_command: list[str]) -> None:
    """Each CLI worker builds the documented command for its binary."""

    worker = create_worker(worker_type)

    assert worker.build_command("Build it.") == expected_command


def test_cli_worker_successful_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A zero exit code produces a successful worker result."""

    monkeypatch.setattr("app.kernel.development.worker.shutil.which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(
        "app.kernel.development.worker.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 0, "ok", ""),
    )

    result = CodexWorker().execute("Implement it.")

    assert result.success is True
    assert result.output == "ok"
    assert result.summary == "codex completed successfully."


def test_cli_worker_uses_explicit_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit executable path replaces argv[0] in the command."""

    captured: list[list[str]] = []

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr("app.kernel.development.worker.shutil.which", lambda _: "/custom/codex")
    monkeypatch.setattr("app.kernel.development.worker.subprocess.run", fake_run)

    result = CodexWorker(executable="/custom/codex").execute("Implement it.")

    assert result.success is True
    assert captured == [["/custom/codex", "exec", "Implement it."]]


def test_cli_worker_failed_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-zero exit code fails the run and surfaces stderr."""

    monkeypatch.setattr("app.kernel.development.worker.shutil.which", lambda _: "/usr/bin/codex")
    monkeypatch.setattr(
        "app.kernel.development.worker.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", "boom\n"),
    )

    result = CodexWorker().execute("Implement it.")

    assert result.success is False
    assert result.summary == "codex failed with exit code 1."
    assert result.output == "boom"


def test_cli_worker_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    """A hanging CLI invocation fails the run with a timeout summary."""

    monkeypatch.setattr("app.kernel.development.worker.shutil.which", lambda _: "/usr/bin/codex")

    def hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="codex", timeout=60, output="partial")

    monkeypatch.setattr("app.kernel.development.worker.subprocess.run", hang)

    result = CodexWorker(timeout=60).execute("Implement it.")

    assert result.success is False
    assert "timed out" in result.summary
    assert result.output == "partial"


def test_cli_worker_detects_modified_files_in_git_repository(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Files created by a worker run appear in the modified-file list."""

    real_run = subprocess.run
    monkeypatch.setattr("app.kernel.development.worker.shutil.which", lambda _: "/usr/bin/codex")

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "codex":
            (tmp_path / "new_file.py").write_text("x = 1\n")
            return subprocess.CompletedProcess(command, 0, "done", "")
        return real_run(command, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("app.kernel.development.worker.subprocess.run", fake_run)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True, capture_output=True, text=True)

    result = CodexWorker(repository=tmp_path).execute("Add a module.")

    assert result.success is True
    assert result.modified_files == [Path("new_file.py")]


# --- Worker registry -------------------------------------------------------


def test_worker_registry_returns_none_when_cli_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unavailable CLIs resolve to no worker."""

    monkeypatch.setattr("app.kernel.development.worker.shutil.which", lambda _: None)

    registry = WorkerRegistry()

    assert registry.get(WorkerType.CODEX) is None
    assert registry.available(WorkerType.CODEX) is False
    assert registry.available_types() == ()


def test_worker_registry_returns_worker_when_cli_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """Installed CLIs resolve to their concrete worker."""

    monkeypatch.setattr("app.kernel.development.worker.shutil.which", lambda _: "/usr/bin/codex")

    registry = WorkerRegistry()
    worker = registry.get(WorkerType.CODEX)

    assert isinstance(worker, CodexWorker)
    assert registry.available(WorkerType.CODEX) is True
    assert WorkerType.CODEX in registry.available_types()


def test_worker_registry_workers_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each call returns a fresh worker instance."""

    monkeypatch.setattr("app.kernel.development.worker.shutil.which", lambda _: "/usr/bin/codex")

    registry = WorkerRegistry()

    assert registry.get(WorkerType.CODEX) is not registry.get(WorkerType.CODEX)


def test_create_worker_returns_concrete_worker_types() -> None:
    """The factory returns the requested worker class for each type."""

    assert isinstance(create_worker(WorkerType.CODEX), CodexWorker)
    assert isinstance(create_worker(WorkerType.AIDER), AiderWorker)
    assert isinstance(create_worker(WorkerType.CLAUDE), ClaudeWorker)
    assert isinstance(create_worker(WorkerType.OPENHANDS), OpenHandsWorker)
