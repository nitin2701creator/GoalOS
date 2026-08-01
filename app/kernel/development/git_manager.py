"""Git safety boundary for the Autonomous Development System."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class GitStatus:
    """Read-only repository status captured by the Git boundary."""

    repository_path: Path


class GitManager:
    """Placeholder interface for controlled repository operations."""

    def __init__(self, repository_path: Path) -> None:
        """Store the repository location for a future Git integration."""

        self.repository_path = repository_path

    def inspect_status(self) -> GitStatus:
        """Return the repository location without mutating it."""

        return GitStatus(repository_path=self.repository_path)
