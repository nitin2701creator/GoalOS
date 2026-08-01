"""Development worker that runs Aider for implementation prompts."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Sequence

from app.kernel.development.worker import WorkerResult
from app.kernel.development.workers.cli_worker import CLIExecution, CLIWorker, ProcessFactory
from app.kernel.development.workers.subprocess_worker import SubprocessWorker


class AiderWorker(CLIWorker):
    """Execute prompts through the local Aider command-line application."""

    def __init__(
        self,
        subprocess_worker: SubprocessWorker | None = None,
        *,
        timeout_seconds: float = 900,
        working_directory: Path | None = None,
        process_factory: ProcessFactory | None = None,
    ) -> None:
        """Initialize with CLI execution and a legacy command-executor adapter."""

        self._subprocess_worker = subprocess_worker
        super().__init__(
            timeout_seconds=timeout_seconds,
            working_directory=working_directory,
            process_factory=process_factory,
        )

    def execute(self, prompt: str) -> WorkerResult:
        """Use the legacy injected executor or the shared CLI worker path."""

        if self._subprocess_worker is not None:
            command = subprocess.list2cmdline(["aider", "--message", prompt])
            return self._subprocess_worker.execute(command)
        return super().execute(prompt)

    def build_command(self, prompt: str) -> Sequence[str]:
        """Build the Aider command for the shared CLI execution path."""

        return ("aider", "--message", prompt)

    def to_worker_result(self, execution: CLIExecution) -> WorkerResult:
        """Map an Aider CLI outcome into the stable ADS result contract."""

        if execution.timed_out:
            return WorkerResult(False, "Aider execution timed out.", execution.output)
        if execution.cancelled:
            return WorkerResult(False, "Aider execution was cancelled.", execution.output)
        if execution.error:
            return WorkerResult(False, "Aider execution failed to start.", execution.output)
        if not execution.succeeded:
            return WorkerResult(
                False,
                f"Aider exited with code {execution.returncode}.",
                execution.output,
            )
        return WorkerResult(True, "Aider execution completed successfully.", execution.output)
