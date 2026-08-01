"""Tests for the Codex ADS development worker."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.kernel.development.worker import DevelopmentWorker
from app.kernel.development.workers.codex_worker import CodexWorker, GitModifiedFilesDetector


class FakeProcess:
    """Controllable process implementation for CLI worker tests."""

    def __init__(
        self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.terminated = False
        self.killed = False

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        return self.stdout, self.stderr

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


def test_codex_worker_implements_development_worker() -> None:
    assert isinstance(CodexWorker(modified_files_detector=lambda: []), DevelopmentWorker)


def test_codex_worker_executes_one_non_interactive_command() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def process_factory(command: tuple[str, ...], **kwargs: object) -> FakeProcess:
        calls.append((command, kwargs))
        return FakeProcess(stdout="Codex changed app.py\n")

    worker = CodexWorker(
        repository_path=Path("repository"),
        process_factory=process_factory,
        modified_files_detector=lambda: [Path("app.py")],
    )

    result = worker.execute('Update "app.py" safely.')

    assert result.success is True
    assert result.output == "Codex changed app.py\n"
    assert result.modified_files == [Path("app.py")]
    assert calls == [
        (
            ("codex", "exec", "--full-auto", 'Update "app.py" safely.'),
            {
                "cwd": Path("repository"),
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "text": True,
            },
        )
    ]


def test_codex_worker_returns_failure_for_nonzero_exit() -> None:
    worker = CodexWorker(
        process_factory=lambda *_args, **_kwargs: FakeProcess(2, "", "failure\n"),
        modified_files_detector=lambda: [Path("should-not-be-read.py")],
    )

    result = worker.execute("Make a change.")

    assert result.success is False
    assert result.summary == "Codex exited with code 2."
    assert result.output == "failure\n"
    assert result.modified_files == []


def test_codex_worker_handles_process_launch_errors() -> None:
    def missing_codex(*_args: object, **_kwargs: object) -> FakeProcess:
        raise FileNotFoundError("codex was not found")

    result = CodexWorker(
        process_factory=missing_codex,
        modified_files_detector=lambda: [],
    ).execute("Make a change.")

    assert result.success is False
    assert result.summary == "Codex execution failed to start."
    assert result.output == "codex was not found"


def test_codex_worker_handles_timeout() -> None:
    class TimeoutProcess(FakeProcess):
        def __init__(self) -> None:
            super().__init__(returncode=-9, stdout="partial\n", stderr="")
            self.calls = 0

        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            self.calls += 1
            if self.calls == 1:
                raise subprocess.TimeoutExpired("codex", timeout, output="partial\n")
            return self.stdout, self.stderr

    process = TimeoutProcess()
    result = CodexWorker(
        timeout_seconds=1,
        process_factory=lambda *_args, **_kwargs: process,
        modified_files_detector=lambda: [],
    ).execute("Make a change.")

    assert result.success is False
    assert result.summary == "Codex execution timed out."
    assert result.output == "partial\n"
    assert process.killed is True


def test_codex_worker_handles_modified_file_detection_errors() -> None:
    def detection_error() -> list[Path]:
        raise RuntimeError("Git unavailable")

    result = CodexWorker(
        process_factory=lambda *_args, **_kwargs: FakeProcess(),
        modified_files_detector=detection_error,
    ).execute("Make a change.")

    assert result.success is True
    assert result.modified_files == []
    assert "could not be detected" in result.summary


def test_git_modified_files_detector_returns_porcelain_paths() -> None:
    completed = subprocess.CompletedProcess(
        args=["git", "status", "--porcelain"],
        returncode=0,
        stdout=" M app/example.py\n?? tests/new_test.py\n",
        stderr="",
    )
    detector = GitModifiedFilesDetector(
        Path("repository"),
        runner=lambda *_args, **_kwargs: completed,
    )

    assert detector() == [Path("app/example.py"), Path("tests/new_test.py")]


def test_codex_worker_cancels_the_active_process() -> None:
    worker: CodexWorker

    class CancellingProcess(FakeProcess):
        def communicate(self, timeout: float | None = None) -> tuple[str, str]:
            assert worker.cancel() is True
            return "", ""

    worker = CodexWorker(
        process_factory=lambda *_args, **_kwargs: CancellingProcess(),
        modified_files_detector=lambda: [],
    )

    result = worker.execute("Make a change.")

    assert result.success is False
    assert result.summary == "Codex execution was cancelled."
