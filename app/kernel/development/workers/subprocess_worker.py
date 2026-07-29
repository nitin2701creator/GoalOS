"""Development worker that executes local subprocess commands."""

from __future__ import annotations

import subprocess

from app.kernel.development.worker import DevelopmentWorker, WorkerResult


class SubprocessWorker(DevelopmentWorker):
    """Execute command strings and return their captured result."""

    def execute(self, prompt: str) -> WorkerResult:
        """Run ``prompt`` as a command and capture its output."""

        try:
            completed = subprocess.run(
                prompt,
                shell=True,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError as error:
            return WorkerResult(
                success=False,
                summary="Command execution failed.",
                output=str(error),
            )

        success = completed.returncode == 0
        return WorkerResult(
            success=success,
            summary=(
                "Command completed successfully."
                if success
                else f"Command exited with code {completed.returncode}."
            ),
            output=completed.stdout + completed.stderr,
        )
