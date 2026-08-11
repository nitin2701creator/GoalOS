"""Test execution boundary for the Autonomous Development System.

The test runner executes a repository's test suite as a bounded
subprocess so the autonomous loop can verify an implementation before
review and commit. Every run is captured as a structured
:class:`TestRun` record that the loop persists and feeds back into
repair prompts.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class TestRun:
    """Outcome of one test-suite execution.

    Attributes:
        command: The test command that was executed.
        passed: Whether the suite exited with a zero status.
        output: Combined stdout/stderr of the run.
        exit_code: Process exit code, or ``None`` when the run timed out.
        duration_seconds: Wall-clock duration of the run.
    """

    command: str
    passed: bool
    output: str
    exit_code: int | None = None
    duration_seconds: float | None = None

    def summary(self, limit: int = 400) -> str:
        """Return a bounded, failure-focused digest of the run output."""
        if self.passed:
            return f"{self.command} passed"
        tail = self.output.strip()[-limit:]
        return f"{self.command} failed:\n{tail}"


class DevelopmentTestRunner:
    """Run a repository's test command with a bounded timeout."""

    def __init__(self, timeout: float = 900.0) -> None:
        """Initialize the runner with a maximum per-run duration."""
        self.timeout = timeout

    def run(self, command: str, cwd: Path | None = None) -> TestRun:
        """Execute ``command`` and return its structured outcome.

        A leading ``python``/``python3`` is resolved to the interpreter
        running GoalOS so the suite always runs inside the project's
        virtual environment. Bytecode is redirected to a throwaway
        ``PYTHONPYCACHEPREFIX`` directory so the suite always compiles
        from the current sources — same-second, same-size edits can
        otherwise leave a stale ``__pycache__`` behind and mask a fix.

        Args:
            command: Shell-style command to execute, e.g.
                ``python -m pytest``.
            cwd: Working directory for the test run.

        Returns:
            The structured test run outcome.
        """
        parts = shlex.split(command)
        if parts and parts[0] in ("python", "python3"):
            parts[0] = sys.executable

        started = time.monotonic()
        try:
            with tempfile.TemporaryDirectory(prefix="ads-pycache-") as cache_dir:
                completed = subprocess.run(
                    parts,
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                    env={**os.environ, "PYTHONPYCACHEPREFIX": cache_dir},
                )
        except subprocess.TimeoutExpired as exc:
            output = (exc.stdout or "") + "\n[test run timed out]"
            return TestRun(
                command=command,
                passed=False,
                output=output.strip(),
                exit_code=None,
            )
        except OSError as exc:  # pragma: no cover - command resolution failure
            return TestRun(
                command=command,
                passed=False,
                output=str(exc),
                exit_code=None,
            )

        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
        return TestRun(
            command=command,
            passed=completed.returncode == 0,
            output=output,
            exit_code=completed.returncode,
            duration_seconds=time.monotonic() - started,
        )
