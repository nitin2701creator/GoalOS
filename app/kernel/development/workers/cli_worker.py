"""Reusable base class for command-line development workers."""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
import logging
from pathlib import Path
import subprocess
from threading import Event, Lock
from typing import Callable, Protocol, Sequence

from app.kernel.development.worker import DevelopmentWorker, WorkerResult


class RunningProcess(Protocol):
    """The subset of ``subprocess.Popen`` used by ``CLIWorker``."""

    returncode: int | None

    def communicate(self, timeout: float | None = None) -> tuple[str, str]: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


ProcessFactory = Callable[..., RunningProcess]


@dataclass(frozen=True, slots=True)
class CLIExecution:
    """Provider-neutral outcome captured from one CLI process."""

    command: tuple[str, ...]
    returncode: int | None
    output: str
    timed_out: bool = False
    cancelled: bool = False
    error: str = ""

    @property
    def succeeded(self) -> bool:
        """Return the generic CLI success mapping for this execution."""

        return not self.timed_out and not self.cancelled and not self.error and self.returncode == 0


class CLIWorker(DevelopmentWorker):
    """Execute one CLI command with timeout, logging, and cancellation support."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 900,
        working_directory: Path | None = None,
        process_factory: ProcessFactory | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self.timeout_seconds = timeout_seconds
        self.working_directory = working_directory
        self._process_factory = process_factory or subprocess.Popen
        self._logger = logger or logging.getLogger(__name__)
        self._active_process: RunningProcess | None = None
        self._process_lock = Lock()
        self._execution_lock = Lock()
        self._cancelled = Event()

    def execute(self, prompt: str) -> WorkerResult:
        """Execute one provider command and let the subclass map its result."""

        with self._execution_lock:
            self._cancelled.clear()
            execution = self._run_command(self.build_command(prompt))
            return self.to_worker_result(execution)

    def cancel(self) -> bool:
        """Request cancellation of the currently running CLI process."""

        with self._process_lock:
            process = self._active_process
            if process is None:
                return False
            self._cancelled.set()
            try:
                process.terminate()
            except OSError as error:
                self._logger.warning("Unable to terminate CLI worker process: %s", error)
            return True

    @abstractmethod
    def build_command(self, prompt: str) -> Sequence[str]:
        """Build the provider-specific command for one ADS prompt."""

    @abstractmethod
    def to_worker_result(self, execution: CLIExecution) -> WorkerResult:
        """Map a provider-neutral CLI outcome into the ADS result contract."""

    def _run_command(self, command: Sequence[str]) -> CLIExecution:
        command_tuple = tuple(command)
        self._logger.info("Starting CLI worker command: %s", command_tuple[0])
        try:
            process = self._process_factory(
                command_tuple,
                cwd=self.working_directory,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as error:
            self._logger.warning("Unable to start CLI worker command: %s", error)
            return CLIExecution(command_tuple, None, str(error), error=str(error))

        with self._process_lock:
            self._active_process = process

        try:
            stdout, stderr = process.communicate(timeout=self.timeout_seconds)
            cancelled = self._cancelled.is_set()
            execution = CLIExecution(
                command_tuple,
                process.returncode,
                self._combine_output(stdout, stderr),
                cancelled=cancelled,
            )
        except subprocess.TimeoutExpired as error:
            try:
                process.kill()
                stdout, stderr = process.communicate()
            except OSError as kill_error:
                execution = CLIExecution(
                    command_tuple,
                    None,
                    str(kill_error),
                    timed_out=True,
                    error=str(kill_error),
                )
            else:
                output = self._combine_output(stdout, stderr)
                if not output:
                    output = self._combine_output(error.output, error.stderr)
                execution = CLIExecution(
                    command_tuple,
                    process.returncode,
                    output,
                    timed_out=True,
                )
        except OSError as error:
            execution = CLIExecution(command_tuple, None, str(error), error=str(error))
        finally:
            with self._process_lock:
                self._active_process = None

        self._logger.info(
            "CLI worker command completed: returncode=%s timed_out=%s cancelled=%s",
            execution.returncode,
            execution.timed_out,
            execution.cancelled,
        )
        return execution

    @staticmethod
    def _combine_output(stdout: str | bytes | None, stderr: str | bytes | None) -> str:
        """Combine process streams while accepting timeout values from subprocess."""

        def as_text(value: str | bytes | None) -> str:
            return value.decode() if isinstance(value, bytes) else value or ""

        return as_text(stdout) + as_text(stderr)
