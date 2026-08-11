"""Worker abstractions for the Autonomous Development System.

The module defines the common :class:`DevelopmentWorker` interface, an
in-memory :class:`MockWorker` for tests, and real subprocess-based workers
for the coding CLIs GoalOS can dispatch to: OpenAI Codex, Aider, Claude
Code, and OpenHands. :class:`WorkerRegistry` resolves a
:class:`WorkerType` to an installed CLI worker and reports which worker
types are available on the current machine.
"""

from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

from app.kernel.development.git_manager import GitManager
from app.kernel.development.models import WorkerType


@dataclass(slots=True)
class WorkerResult:
    """The result returned by a development worker."""

    success: bool
    summary: str
    output: str
    modified_files: list[Path] = field(default_factory=list)


class WorkerUnavailableError(RuntimeError):
    """Raised when a requested CLI worker's executable is not installed."""


class DevelopmentWorker(ABC):
    """Common interface for development workers."""

    @abstractmethod
    def execute(self, prompt: str) -> WorkerResult:
        """Execute a prompt and return its worker result."""


class MockWorker(DevelopmentWorker):
    """In-memory worker implementation for tests."""

    def __init__(self) -> None:
        """Initialize the worker without a received prompt."""

        self.prompt: str | None = None

    def execute(self, prompt: str) -> WorkerResult:
        """Record ``prompt`` and return a successful mock result."""

        self.prompt = prompt
        return WorkerResult(
            success=True,
            summary="Mock execution completed.",
            output=prompt,
        )


class CLIWorker(DevelopmentWorker):
    """Base class for workers that dispatch to a coding CLI subprocess.

    Subclasses declare the CLI ``binary`` and how to build the command
    list from a prompt. Execution runs the CLI as a subprocess with a
    bounded timeout, captures stdout/stderr, and — when running inside a
    Git repository — records which files changed during the run using
    the read-only :class:`GitManager`.
    """

    binary: ClassVar[str]

    def __init__(
        self,
        repository: Path | None = None,
        timeout: float = 600.0,
        executable: str | None = None,
    ) -> None:
        """Initialize the CLI worker.

        Args:
            repository: Repository root the worker runs in and inspects
                for changed files; when ``None``, the current working
                directory is used for execution and change detection is
                disabled.
            timeout: Maximum seconds a CLI invocation may run.
            executable: Optional explicit path to the CLI binary used as
                the subprocess ``argv[0]``; when omitted the binary name
                is resolved from ``PATH``.
        """
        self.repository = repository
        self.timeout = timeout
        self.executable = executable
        self._git_manager = GitManager(repository) if repository is not None else None

    def available(self) -> bool:
        """Return whether the CLI executable can be resolved on this machine."""
        return shutil.which(self.executable or self.binary) is not None

    @property
    def worker_type(self) -> WorkerType:
        """The worker type this CLI worker implements."""
        raise NotImplementedError

    def build_command(self, prompt: str) -> list[str]:
        """Build the CLI command list for ``prompt``."""
        raise NotImplementedError

    def execute(self, prompt: str) -> WorkerResult:
        """Run the CLI with ``prompt`` and return its worker result.

        Raises:
            WorkerUnavailableError: If the CLI executable is not installed.
        """
        if not self.available():
            raise WorkerUnavailableError(
                f"{self.binary} is not installed or not on PATH; "
                f"install it to use the {self.worker_type.value} worker"
            )

        before = self._git_manager.uncommitted_changes() if self._git_manager else ()
        command = self.build_command(prompt)
        if self.executable is not None:
            command = [self.executable, *command[1:]]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=self.repository,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return WorkerResult(
                success=False,
                summary=f"{self.binary} timed out after {self.timeout:g} seconds.",
                output=exc.stdout or "",
            )
        except OSError as exc:
            return WorkerResult(
                success=False,
                summary=f"{self.binary} could not be started.",
                output=str(exc),
            )

        output = self._combine_output(completed)
        if not completed.stdout:
            output = (completed.stderr or "").strip()
        modified_files = self._changed_files(before)
        summary = (
            f"{self.binary} completed successfully."
            if completed.returncode == 0
            else f"{self.binary} failed with exit code {completed.returncode}."
        )
        return WorkerResult(
            success=completed.returncode == 0,
            summary=summary,
            output=output,
            modified_files=modified_files,
        )

    def _changed_files(self, before: tuple[Path, ...]) -> list[Path]:
        """Return files that appeared in Git status during this execution."""
        if self._git_manager is None:
            return []
        after = self._git_manager.uncommitted_changes()
        return list(self._git_manager.changed_since(before, after))

    @staticmethod
    def _combine_output(completed: subprocess.CompletedProcess[str]) -> str:
        """Join stdout and stderr into a single text artifact."""
        parts = [part for part in (completed.stdout, completed.stderr) if part]
        return "\n".join(parts).strip()


class CodexWorker(CLIWorker):
    """Worker that dispatches to the OpenAI Codex CLI (``codex exec``)."""

    binary: ClassVar[str] = "codex"

    @property
    def worker_type(self) -> WorkerType:
        return WorkerType.CODEX

    def build_command(self, prompt: str) -> list[str]:
        return ["codex", "exec", prompt]


class AiderWorker(CLIWorker):
    """Worker that dispatches to Aider (``aider --message``)."""

    binary: ClassVar[str] = "aider"

    @property
    def worker_type(self) -> WorkerType:
        return WorkerType.AIDER

    def build_command(self, prompt: str) -> list[str]:
        return ["aider", "--message", prompt, "--yes"]


class ClaudeWorker(CLIWorker):
    """Worker that dispatches to Claude Code (``claude -p``)."""

    binary: ClassVar[str] = "claude"

    @property
    def worker_type(self) -> WorkerType:
        return WorkerType.CLAUDE

    def build_command(self, prompt: str) -> list[str]:
        return ["claude", "-p", prompt, "--output-format", "text"]


class OpenHandsWorker(CLIWorker):
    """Worker that dispatches to the OpenHands CLI (``openhands run``)."""

    binary: ClassVar[str] = "openhands"

    @property
    def worker_type(self) -> WorkerType:
        return WorkerType.OPENHANDS

    def build_command(self, prompt: str) -> list[str]:
        return ["openhands", "run", "--task", prompt]


def _worker_factory(worker_type: WorkerType) -> Callable[..., CLIWorker] | None:
    """Return the CLI worker class constructor for ``worker_type``."""
    return _WORKER_CLASSES.get(worker_type)


_WORKER_CLASSES: dict[WorkerType, type[CLIWorker]] = {
    WorkerType.AIDER: AiderWorker,
    WorkerType.CODEX: CodexWorker,
    WorkerType.CLAUDE: ClaudeWorker,
    WorkerType.OPENHANDS: OpenHandsWorker,
}


class WorkerRegistry:
    """Resolve worker types to installed CLI workers.

    The registry maps every supported :class:`WorkerType` to a factory
    for its CLI worker. ``get`` returns a worker only when its CLI
    executable is available; callers can therefore fall back to another
    worker or surface an explicit unavailability error.
    """

    def __init__(
        self,
        repository: Path | None = None,
        timeout: float = 600.0,
    ) -> None:
        """Initialize the registry with factories for every worker type."""
        self.repository = repository
        self.timeout = timeout

    def get(self, worker_type: WorkerType) -> CLIWorker | None:
        """Return an installed worker for ``worker_type``, else ``None``."""
        worker_class = _WORKER_CLASSES.get(worker_type)
        if worker_class is None:
            return None
        worker = worker_class(self.repository, self.timeout)
        if not worker.available():
            return None
        return worker

    def available(self, worker_type: WorkerType) -> bool:
        """Return whether the CLI for ``worker_type`` is installed."""
        return self.get(worker_type) is not None

    def available_types(self) -> tuple[WorkerType, ...]:
        """Return every worker type whose CLI is installed, in stable order."""
        return tuple(worker_type for worker_type in _WORKER_CLASSES if self.available(worker_type))


def create_worker(
    worker_type: WorkerType,
    repository: Path | None = None,
    timeout: float = 600.0,
) -> DevelopmentWorker:
    """Create a CLI worker for ``worker_type`` without an availability check.

    The returned worker raises :class:`WorkerUnavailableError` when its
    CLI executable is missing at execution time. Prefer
    :meth:`WorkerRegistry.get` when availability matters up front.

    Raises:
        ValueError: If ``worker_type`` is not a supported worker type.
    """
    worker_class = _WORKER_CLASSES.get(worker_type)
    if worker_class is None:
        raise ValueError(f"Unsupported worker type: {worker_type}")
    return worker_class(repository, timeout)
