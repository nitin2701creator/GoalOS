"""Codex-backed implementation of the ADS development-worker interface."""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
from typing import Callable, Sequence

from app.kernel.development.worker import WorkerResult
from app.kernel.development.workers.cli_worker import CLIExecution, CLIWorker, ProcessFactory


ModifiedFilesDetector = Callable[[], list[Path]]


class GitModifiedFilesDetector:
    """Read modified paths from Git without changing the working tree."""

    def __init__(
        self,
        repository_path: Path,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.repository_path = repository_path
        self._runner = runner or subprocess.run

    def __call__(self) -> list[Path]:
        completed = self._runner(
            ["git", "status", "--porcelain"],
            cwd=self.repository_path,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "Unable to inspect Git status.")

        return [
            Path(line[3:].split(" -> ")[-1])
            for line in completed.stdout.splitlines()
            if len(line) > 3
        ]


class CodexWorker(CLIWorker):
    """Execute one ADS prompt through the Codex command-line engine."""

    def __init__(
        self,
        *,
        executable: str = "codex",
        arguments: Sequence[str] = ("exec", "--full-auto"),
        repository_path: Path | None = None,
        modified_files_detector: ModifiedFilesDetector | None = None,
        timeout_seconds: float = 900,
        process_factory: ProcessFactory | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.executable = executable
        self.arguments = tuple(arguments)
        self.repository_path = repository_path or Path.cwd()
        self._modified_files_detector = (
            modified_files_detector or GitModifiedFilesDetector(self.repository_path)
        )
        super().__init__(
            timeout_seconds=timeout_seconds,
            working_directory=self.repository_path,
            process_factory=process_factory,
            logger=logger,
        )

    def build_command(self, prompt: str) -> tuple[str, ...]:
        """Build one non-interactive Codex command from an ADS prompt."""

        return (self.executable, *self.arguments, prompt)

    def to_worker_result(self, execution: CLIExecution) -> WorkerResult:
        """Convert the Codex command outcome into the stable ADS result type."""

        if execution.timed_out:
            return WorkerResult(False, "Codex execution timed out.", execution.output)
        if execution.cancelled:
            return WorkerResult(False, "Codex execution was cancelled.", execution.output)
        if execution.error:
            return WorkerResult(False, "Codex execution failed to start.", execution.output)
        if not execution.succeeded:
            return WorkerResult(
                False,
                f"Codex exited with code {execution.returncode}.",
                execution.output,
            )

        try:
            modified_files = self._modified_files_detector()
        except Exception as error:  # Metadata must never mask Codex execution.
            self._logger.warning("Unable to detect Codex modified files: %s", error)
            return WorkerResult(
                True,
                "Codex execution completed; modified files could not be detected.",
                execution.output,
            )

        return WorkerResult(
            True,
            "Codex execution completed successfully.",
            execution.output,
            modified_files=modified_files,
        )
