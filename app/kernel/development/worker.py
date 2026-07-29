"""Worker abstractions for the Autonomous Development System."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class WorkerResult:
    """The result returned by a development worker."""

    success: bool
    summary: str
    output: str
    modified_files: list[Path] = field(default_factory=list)


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
