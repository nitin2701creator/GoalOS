"""Domain models for the Autonomous Development System."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

from app.compat import StrEnum


class TaskStatus(StrEnum):
    """Lifecycle states for a development task."""

    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    FAILED = "failed"
    COMPLETED = "completed"


class WorkerType(StrEnum):
    """Supported workers for development tasks."""

    AIDER = "aider"
    CODEX = "codex"
    CLAUDE = "claude"
    OPENHANDS = "openhands"


@dataclass(slots=True)
class DevelopmentTask:
    """A unit of development work managed by ADS."""

    title: str
    description: str
    id: UUID = field(default_factory=uuid4, kw_only=True)
    files: list[Path] = field(default_factory=list)
    worker: WorkerType = WorkerType.CODEX
    status: TaskStatus = TaskStatus.PENDING
    test_command: str = "python -m pytest"
    commit_message: str = ""
    dependencies: list[UUID] = field(default_factory=list)
